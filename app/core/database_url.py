"""Building a Postgres URL out of its separate parts.

This lives here, rather than inside `Settings`, because two callers need the
same rule and only one of them goes through `Settings`. The application reads
its configuration through `Settings`; Alembic does not -- `migrations/env.py`
is its own entry point and only ever sees environment variables. When the rule
lived in one of them, the other had to restate it, and a restated rule is one
that eventually disagrees with itself.

Deliberately dependency-free: only the standard library, and nothing from
`app.core.config`. Importing this module executes an empty `app/core/__init__`
and nothing else, so Alembic does not drag the YAML config and the settings
stack along with it just to learn how to punctuate a URL.
"""

from urllib.parse import quote


def build_database_url(
    *,
    host: str | None,
    port: int | str | None,
    name: str | None,
    user: str | None,
    password: str | None,
) -> str | None:
    """Assemble `postgresql://user:password@host:port/name`.

    Returns None when any required part is missing, which is what lets a
    caller treat "no parts configured" and "parts incomplete" the same way:
    there is no URL to be had, and the caller decides whether that is an error.
    `port` is the exception -- it falls back to 5432, the only part with a
    meaningful default.

    The user and password are percent-encoded. RDS generates the password and
    does not promise it is URL-safe: an `@` or a `/` inside it would otherwise
    be read as the delimiter it looks like, splitting the URL at the wrong
    place. That failure surfaces as an unresolvable host, which points nowhere
    near the password -- and it cannot reproduce locally, where the
    docker-compose password is plain.
    """
    if not all((host, name, user, password)):
        return None

    return (
        f"postgresql://{quote(user or '', safe='')}"
        f":{quote(password or '', safe='')}"
        f"@{host}:{port or 5432}/{name}"
    )
