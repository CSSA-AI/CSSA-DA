"""Create or update the database role the API runs as.

Two identities touch the production database, and they should never be the
same one (ROADMAP_platform item 20):

- the **migration identity** (the RDS master user) runs ``alembic upgrade
  head``, which includes ``CREATE EXTENSION vector`` -- something an ordinary
  role cannot do -- and owns every table the migrations create;
- the **runtime identity** is what the long-running, internet-facing API
  connects as. It can read the knowledge base and append interactions, and
  nothing else: no DDL, no ownership, no writes to the corpus.

This script is run *as the migration identity*, right after the migrations:

    RUNTIME_DB_PASSWORD=... python -m ops.provision_runtime_role

It is declarative and idempotent. ``RUNTIME_TABLE_PRIVILEGES`` below is the
complete privilege set: each run revokes everything and grants exactly that,
in one transaction, so a privilege removed from the list is removed from the
database on the next run, and no other session ever sees a half-applied state.
Re-running it with a new password rotates the password.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import encrypt_password

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import rag_config, settings


DEFAULT_RUNTIME_ROLE = "cssa_app"
SCHEMA = "public"
MIN_PASSWORD_LENGTH = 16

# Every table the running API touches, and the least it needs there. Local
# development and CI connect as a superuser, so a code path that reads or
# writes a table missing from this list works everywhere except production,
# where it fails with "permission denied". A new query against a new table
# needs its line here in the same change;
# tests/integration/test_runtime_role.py drives the real code paths as this
# role to catch the ones that forget.
RUNTIME_TABLE_PRIVILEGES: dict[str, tuple[str, ...]] = {
    # Retriever search and the /ready row count.
    rag_config["pgvector"]["table_name"]: ("SELECT",),
    # /status reports the latest pipeline run.
    "pipeline_runs": ("SELECT",),
    # One row per answered /v1/chat. The API appends users' questions and
    # answers but cannot read anyone's back, so a compromised API process
    # cannot dump the interaction log. The one column it may read is
    # request_id: the write is INSERT ... ON CONFLICT (request_id) DO NOTHING,
    # and Postgres requires SELECT on a conflict target's columns. Without it
    # every write is refused -- and silently, because the write runs after
    # the response and only logs its failures.
    "chat_interactions": ("INSERT", "SELECT (request_id)"),
}

# Attributes that would let the runtime role do what the migration identity
# does. A pre-existing role carrying any of them is someone else's account,
# and this script refuses to silently repurpose it.
ELEVATED_ATTRIBUTES = (
    "rolsuper",
    "rolcreaterole",
    "rolcreatedb",
    "rolreplication",
    "rolbypassrls",
)


class ProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvisionResult:
    role: str
    created: bool
    table_privileges: dict[str, tuple[str, ...]]


def provision_runtime_role(
    database_url: str,
    role: str,
    password: str,
) -> ProvisionResult:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ProvisioningError(
            f"RUNTIME_DB_PASSWORD must be at least {MIN_PASSWORD_LENGTH} "
            "characters"
        )

    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                created = _apply(connection, cursor, role, password)
                _verify(cursor, role)
    finally:
        connection.close()

    return ProvisionResult(
        role=role,
        created=created,
        table_privileges=dict(RUNTIME_TABLE_PRIVILEGES),
    )


def _apply(connection: Any, cursor: Any, role: str, password: str) -> bool:
    cursor.execute("SELECT current_user, current_database();")
    current_user, database = cursor.fetchone()
    if role == current_user:
        raise ProvisioningError(
            f"refusing to provision {role!r}: that is the identity this "
            "script is connected as. Connect as the migration identity and "
            "provision a separate role for the API."
        )

    missing = [
        table
        for table in RUNTIME_TABLE_PRIVILEGES
        if not _table_exists(cursor, table)
    ]
    if missing:
        raise ProvisioningError(
            f"tables do not exist yet: {', '.join(missing)}. "
            "Run `alembic upgrade head` first."
        )

    cursor.execute(
        "SELECT " + ", ".join(ELEVATED_ATTRIBUTES)
        + " FROM pg_roles WHERE rolname = %s;",
        (role,),
    )
    attributes = cursor.fetchone()
    if attributes is not None and any(attributes):
        elevated = [
            name
            for name, value in zip(ELEVATED_ATTRIBUTES, attributes)
            if value
        ]
        raise ProvisioningError(
            f"role {role!r} already exists with {', '.join(elevated)}; "
            "refusing to reuse a privileged account as the runtime role"
        )

    # Hashed here, not on the server: the statement then carries a SCRAM
    # verifier instead of the password, so the plaintext never lands in the
    # server log or pg_stat_statements.
    verifier = encrypt_password(password, role, connection, "scram-sha-256")
    created = attributes is None
    verb = "CREATE" if created else "ALTER"
    cursor.execute(
        sql.SQL(
            verb + " ROLE {role} WITH LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {verifier}"
        ).format(role=sql.Identifier(role), verifier=sql.Literal(verifier))
    )

    role_id = sql.Identifier(role)
    schema_id = sql.Identifier(SCHEMA)
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {};").format(
            sql.Identifier(database), role_id
        )
    )
    cursor.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {};").format(schema_id, role_id)
    )
    # Converge rather than accumulate: start from nothing on every table and
    # sequence in the schema, then grant exactly the list.
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {};").format(
            schema_id, role_id
        )
    )
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM {};").format(
            schema_id, role_id
        )
    )
    for table, privileges in RUNTIME_TABLE_PRIVILEGES.items():
        cursor.execute(
            sql.SQL("GRANT {} ON TABLE {}.{} TO {};").format(
                sql.SQL(", ").join(sql.SQL(p) for p in privileges),
                schema_id,
                sql.Identifier(table),
                role_id,
            )
        )
    return created


def _verify(cursor: Any, role: str) -> None:
    # The point of the second identity is what it cannot do. Check that
    # directly instead of trusting the statements above.
    cursor.execute(
        """
        SELECT
            has_schema_privilege(%s, %s, 'CREATE'),
            has_database_privilege(%s, current_database(), 'CREATE'),
            (SELECT COUNT(*) FROM pg_class c
               JOIN pg_roles r ON r.oid = c.relowner
              WHERE r.rolname = %s),
            (SELECT COUNT(*) FROM pg_auth_members m
               JOIN pg_roles r ON r.oid = m.member
              WHERE r.rolname = %s);
        """,
        (role, SCHEMA, role, role, role),
    )
    can_create_in_schema, can_create_schema, owned, memberships = (
        cursor.fetchone()
    )
    problems = []
    if can_create_in_schema:
        problems.append(f"can create objects in schema {SCHEMA}")
    if can_create_schema:
        problems.append("can create schemas in this database")
    if owned:
        problems.append(f"owns {owned} relation(s)")
    if memberships:
        problems.append(
            f"is a member of {memberships} other role(s), whose privileges "
            "it inherits"
        )
    if problems:
        raise ProvisioningError(
            f"role {role!r} is not least-privilege: {'; '.join(problems)}"
        )


def _table_exists(cursor: Any, table: str) -> bool:
    cursor.execute(
        "SELECT to_regclass(%s);",
        (f"{SCHEMA}.{table}",),
    )
    return cursor.fetchone()[0] is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update the least-privilege role the API connects "
            "as. Run as the migration identity, after the migrations. The "
            "password is read from RUNTIME_DB_PASSWORD, never from argv."
        )
    )
    parser.add_argument(
        "--database-url",
        default=settings.DATABASE_URL,
        help="Migration identity's connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--role",
        default=os.getenv("RUNTIME_DB_USER", DEFAULT_RUNTIME_ROLE),
        help=(
            "Runtime role name. Defaults to RUNTIME_DB_USER, else "
            f"{DEFAULT_RUNTIME_ROLE}."
        ),
    )
    args = parser.parse_args(argv)

    password = os.getenv("RUNTIME_DB_PASSWORD")
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if not password:
        parser.error("RUNTIME_DB_PASSWORD is required")

    try:
        result = provision_runtime_role(args.database_url, args.role, password)
    except ProvisioningError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"Runtime role {result.role}: "
        f"{'created' if result.created else 'updated'}"
    )
    for table, privileges in result.table_privileges.items():
        print(f"  {table}: {', '.join(privileges)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
