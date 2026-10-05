import pytest

from app.core.database_url import build_database_url


def test_assembles_the_parts_in_order():
    assert build_database_url(
        host="cssa-da-prod-db.ap-southeast-2.rds.amazonaws.com",
        port=5432,
        name="rag_vectordb",
        user="cssa_admin",
        password="plain",
    ) == (
        "postgresql://cssa_admin:plain"
        "@cssa-da-prod-db.ap-southeast-2.rds.amazonaws.com:5432/rag_vectordb"
    )


def test_credentials_are_percent_encoded():
    # RDS generates the password and does not promise it is URL-safe. Without
    # encoding, the '@' below ends the credentials early and the rest parses as
    # part of the host -- which surfaces as an unresolvable host rather than as
    # a credential problem, pointing debugging in the wrong direction.
    assert build_database_url(
        host="db.internal",
        port=5432,
        name="rag_vectordb",
        user="cssa_admin",
        password="p@ss/word:1+2=3",
    ) == (
        "postgresql://cssa_admin:p%40ss%2Fword%3A1%2B2%3D3"
        "@db.internal:5432/rag_vectordb"
    )


def test_port_arrives_as_a_string_from_the_environment():
    # os.getenv gives strings, so Alembic passes one here while Settings passes
    # an int. Both have to produce the same URL.
    assert build_database_url(
        host="db.internal",
        port="5432",
        name="rag_vectordb",
        user="u",
        password="p",
    ) == build_database_url(
        host="db.internal",
        port=5432,
        name="rag_vectordb",
        user="u",
        password="p",
    )


def test_port_falls_back_to_the_postgres_default():
    url = build_database_url(
        host="db.internal",
        port=None,
        name="rag_vectordb",
        user="u",
        password="p",
    )

    assert url == "postgresql://u:p@db.internal:5432/rag_vectordb"


@pytest.mark.parametrize("missing", ["host", "name", "user", "password"])
def test_returns_none_when_a_required_part_is_missing(missing):
    parts = {
        "host": "db.internal",
        "port": 5432,
        "name": "rag_vectordb",
        "user": "u",
        "password": "p",
    }
    parts[missing] = None

    assert build_database_url(**parts) is None


def test_returns_none_when_a_required_part_is_empty():
    # An unset ECS secret arrives as an empty string rather than as absent, so
    # emptiness has to count as missing too -- otherwise this builds a URL with
    # no password and the failure moves to the database, as an auth error.
    assert (
        build_database_url(
            host="db.internal",
            port=5432,
            name="rag_vectordb",
            user="u",
            password="",
        )
        is None
    )
