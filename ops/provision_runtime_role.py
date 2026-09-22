"""Create or update the database role the API runs as.

Two identities touch the production database, and they should never be the
same one (ROADMAP_platform item 20):

- the **migration identity** (the RDS master user) runs ``alembic upgrade
  head``, which includes ``CREATE EXTENSION vector`` -- something an ordinary
  role cannot do -- owns every table the migrations create, and loads the
  corpus;
- the **runtime identity** is what the long-running, internet-facing API
  connects as. It can read the knowledge base and append interactions, and
  nothing else: no DDL, no ownership, no writes to the corpus.

This script is run *as the migration identity*, right after the migrations
(the migrate task does both on every deploy):

    RUNTIME_DB_PASSWORD=... python -m ops.provision_runtime_role

It is declarative and idempotent for privileges. ``RUNTIME_TABLE_PRIVILEGES``
and ``RUNTIME_COLUMN_PRIVILEGES`` below are the complete set: each run revokes
what the migration identity granted and grants exactly the lists, in one
transaction, then checks the role's *effective* privileges on every table,
column and sequence in every schema the role can reach -- which also catches
anything that arrives another way, such as a grant to PUBLIC. Re-running with
the same password changes nothing; with a new one it rotates the password (see
docs/deployment.md for the order that avoids an outage).

Deliberately left alone: per-role settings (ALTER ROLE ... SET) and the
connection limit, which an operator may set on purpose (a statement_timeout, a
connection budget). The password is always set to never expire, so the API
cannot be locked out on a date nobody remembers choosing.

It works as the RDS master user, which is *not* a superuser: on PostgreSQL 16
such a role may create a role with NOSUPERUSER/NOREPLICATION/NOBYPASSRLS but
may not name those attributes again in ALTER ROLE, so the update path only
touches LOGIN and the password.
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
# writes a table missing from these lists works everywhere except production,
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
    # cannot dump the interaction log.
    "chat_interactions": ("INSERT",),
}

# Column-level grants, for the few places where a whole-table privilege would
# be too much.
RUNTIME_COLUMN_PRIVILEGES: dict[str, dict[str, tuple[str, ...]]] = {
    # The interaction write is INSERT ... ON CONFLICT (request_id) DO NOTHING,
    # and Postgres requires SELECT on a conflict target's columns. Without it
    # every write is refused -- and silently, because the write runs after the
    # response and only logs its failures. request_id is the only column the
    # API can read.
    "chat_interactions": {"SELECT": ("request_id",)},
}

TABLE_PRIVILEGE_TYPES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
COLUMN_PRIVILEGE_TYPES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
SEQUENCE_PRIVILEGE_TYPES = ("USAGE", "SELECT", "UPDATE")

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

# Relation kinds that carry table privileges: tables, partitioned tables,
# views, materialized views and foreign tables.
TABLE_LIKE_RELKINDS = ("r", "p", "v", "m", "f")


class ProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvisionResult:
    role: str
    created: bool
    table_privileges: dict[str, tuple[str, ...]]
    column_privileges: dict[str, dict[str, tuple[str, ...]]]


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
        column_privileges={
            table: dict(columns)
            for table, columns in RUNTIME_COLUMN_PRIVILEGES.items()
        },
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

    granted_tables = set(RUNTIME_TABLE_PRIVILEGES) | set(
        RUNTIME_COLUMN_PRIVILEGES
    )
    missing = [
        table
        for table in sorted(granted_tables)
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
    verifier = sql.Literal(
        encrypt_password(password, role, connection, "scram-sha-256")
    )
    role_id = sql.Identifier(role)
    created = attributes is None
    if created:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {} "
                "VALID UNTIL 'infinity';"
            ).format(role_id, verifier)
        )
    else:
        # LOGIN and the password only. A non-superuser (the RDS master) may
        # not name SUPERUSER, REPLICATION or BYPASSRLS in ALTER ROLE at all --
        # not even to turn them off -- and the check above already refused a
        # role that has any of them.
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} WITH LOGIN PASSWORD {} VALID UNTIL 'infinity';"
            ).format(role_id, verifier)
        )

    schema_id = sql.Identifier(SCHEMA)
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {};").format(
            sql.Identifier(database), role_id
        )
    )
    cursor.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {};").format(schema_id, role_id)
    )

    # Converge rather than accumulate: start from nothing, then grant exactly
    # the lists. Only on relations this identity manages -- REVOKE on a
    # relation owned by a role it has no rights on is an error, not a no-op,
    # and would abort the run. Anything left over on such a relation is
    # caught by _verify, which looks at effective privileges.
    cursor.execute(
        """
        SELECT c.relname, c.relkind = 'S'
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND pg_has_role(current_user, c.relowner, 'USAGE')
        ORDER BY c.relname;
        """,
        (SCHEMA,),
    )
    for relname, is_sequence in cursor.fetchall():
        cursor.execute(
            sql.SQL("REVOKE ALL ON {} {}.{} FROM {};").format(
                sql.SQL("SEQUENCE" if is_sequence else "TABLE"),
                schema_id,
                sql.Identifier(relname),
                role_id,
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
    for table, by_privilege in RUNTIME_COLUMN_PRIVILEGES.items():
        for privilege, columns in by_privilege.items():
            cursor.execute(
                sql.SQL("GRANT {} ({}) ON TABLE {}.{} TO {};").format(
                    sql.SQL(privilege),
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    schema_id,
                    sql.Identifier(table),
                    role_id,
                )
            )
    return created


def _verify(cursor: Any, role: str) -> None:
    # The point of the second identity is what it cannot do. Check the role's
    # effective capabilities -- whatever route they arrive by -- instead of
    # trusting the statements above.
    problems = _attribute_problems(cursor, role)
    problems += _ownership_problems(cursor, role)
    problems += _privilege_problems(cursor, role)
    if problems:
        raise ProvisioningError(
            f"role {role!r} is not least-privilege:\n  - "
            + "\n  - ".join(problems)
        )


def _attribute_problems(cursor: Any, role: str) -> list[str]:
    cursor.execute(
        "SELECT " + ", ".join(ELEVATED_ATTRIBUTES)
        + """,
            (SELECT COUNT(*) FROM pg_auth_members m WHERE m.member = r.oid),
            has_database_privilege(r.oid, current_database(), 'CREATE')
        FROM pg_roles r WHERE r.rolname = %s;
        """,
        (role,),
    )
    *attributes, memberships, can_create_schema = cursor.fetchone()
    problems = [
        f"has {name}"
        for name, value in zip(ELEVATED_ATTRIBUTES, attributes)
        if value
    ]
    if memberships:
        problems.append(
            f"is a member of {memberships} other role(s), whose privileges "
            "it inherits"
        )
    if can_create_schema:
        problems.append("can create schemas in this database")
    return problems


def _ownership_problems(cursor: Any, role: str) -> list[str]:
    cursor.execute(
        """
        SELECT 'owns relation ' || n.nspname || '.' || c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relowner = (SELECT oid FROM pg_roles WHERE rolname = %s)
        UNION ALL
        SELECT 'owns schema ' || n.nspname
        FROM pg_namespace n
        WHERE n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = %s)
        UNION ALL
        SELECT 'can create objects in schema ' || n.nspname
        FROM pg_namespace n
        WHERE n.nspname NOT LIKE 'pg\\_%%'
          AND n.nspname <> 'information_schema'
          AND has_schema_privilege(%s, n.oid, 'CREATE')
        ORDER BY 1;
        """,
        (role, role, role),
    )
    return [row[0] for row in cursor.fetchall()]


def _privilege_problems(cursor: Any, role: str) -> list[str]:
    # has_*_privilege answers for the role as it would actually be checked:
    # direct grants, grants from any grantor, and grants to PUBLIC alike.
    # Every schema the role can reach, not only public: a table another
    # schema grants to PUBLIC is as readable as one in public.
    reachable = """
        n.nspname NOT LIKE 'pg\\_%%'
        AND n.nspname <> 'information_schema'
        AND has_schema_privilege(%(role)s, n.oid, 'USAGE')
    """
    cursor.execute(
        """
        SELECT n.nspname || '.' || c.relname, p.privilege
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN unnest(%(privileges)s::text[]) AS p(privilege)
        WHERE """ + reachable + """
          AND c.relkind = ANY(%(relkinds)s::"char"[])
          AND has_table_privilege(%(role)s, c.oid, p.privilege);
        """,
        {
            "privileges": list(TABLE_PRIVILEGE_TYPES),
            "relkinds": list(TABLE_LIKE_RELKINDS),
            "role": role,
        },
    )
    actual_table = set(cursor.fetchall())
    expected_table = {
        (f"{SCHEMA}.{table}", privilege)
        for table, privileges in RUNTIME_TABLE_PRIVILEGES.items()
        for privilege in privileges
    }

    # A column counts when the role holds the privilege on that column but
    # not on the whole table -- whole-table privileges are compared above.
    cursor.execute(
        """
        SELECT n.nspname || '.' || c.relname, a.attname, p.privilege
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a
          ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        CROSS JOIN unnest(%(privileges)s::text[]) AS p(privilege)
        WHERE """ + reachable + """
          AND c.relkind = ANY(%(relkinds)s::"char"[])
          AND has_column_privilege(%(role)s, c.oid, a.attnum, p.privilege)
          AND NOT has_table_privilege(%(role)s, c.oid, p.privilege);
        """,
        {
            "privileges": list(COLUMN_PRIVILEGE_TYPES),
            "relkinds": list(TABLE_LIKE_RELKINDS),
            "role": role,
        },
    )
    actual_column = set(cursor.fetchall())
    expected_column = {
        (f"{SCHEMA}.{table}", column, privilege)
        for table, by_privilege in RUNTIME_COLUMN_PRIVILEGES.items()
        for privilege, columns in by_privilege.items()
        for column in columns
    }

    cursor.execute(
        """
        SELECT n.nspname || '.' || c.relname, p.privilege
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN unnest(%(privileges)s::text[]) AS p(privilege)
        WHERE """ + reachable + """
          AND c.relkind = 'S'
          AND has_sequence_privilege(%(role)s, c.oid, p.privilege);
        """,
        {"privileges": list(SEQUENCE_PRIVILEGE_TYPES), "role": role},
    )
    sequence_grants = sorted(cursor.fetchall())

    problems = [
        f"has {privilege} on {table}, which is not in the list"
        for table, privilege in sorted(actual_table - expected_table)
    ]
    problems += [
        f"lacks {privilege} on {table}"
        for table, privilege in sorted(expected_table - actual_table)
    ]
    problems += [
        f"has {privilege} on {table}.{column}, which is not in the list"
        for table, column, privilege in sorted(actual_column - expected_column)
    ]
    problems += [
        f"lacks {privilege} on {table}.{column}"
        for table, column, privilege in sorted(expected_column - actual_column)
    ]
    problems += [
        f"has {privilege} on sequence {sequence}"
        for sequence, privilege in sequence_grants
    ]
    if actual_table - expected_table or actual_column - expected_column:
        problems.append(
            "privileges this script did not grant usually come from a GRANT "
            "to PUBLIC or from another grantor; this script does not revoke "
            "those, because they affect other roles too"
        )
    return problems


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
        help=(
            "Migration identity's connection URL. Defaults to DATABASE_URL, "
            "or the URL assembled from DB_HOST/DB_PORT/DB_NAME/DB_USER/"
            "DB_PASSWORD."
        ),
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
    for table, by_privilege in result.column_privileges.items():
        for privilege, columns in by_privilege.items():
            print(f"  {table} ({', '.join(columns)}): {privilege}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
