from unittest.mock import patch

import pytest

from app.core.config import rag_config
from ops import provision_runtime_role as provision


def test_runtime_role_can_only_read_the_corpus():
    # The API faces the internet; the corpus is written by the import, which
    # runs under the migration identity. A write privilege here would let a
    # compromised API poison every future answer.
    table = rag_config["pgvector"]["table_name"]

    assert provision.RUNTIME_TABLE_PRIVILEGES[table] == ("SELECT",)


def test_runtime_role_cannot_read_the_interaction_log():
    # Only the conflict-target column, which ON CONFLICT (request_id) needs;
    # never the queries and answers themselves.
    privileges = provision.RUNTIME_TABLE_PRIVILEGES["chat_interactions"]

    assert set(privileges) == {"INSERT", "SELECT (request_id)"}


@patch("ops.provision_runtime_role.psycopg2.connect")
def test_short_password_is_refused_before_connecting(mock_connect):
    with pytest.raises(provision.ProvisioningError, match="at least 16"):
        provision.provision_runtime_role(
            "postgresql://admin:pw@db:5432/rag_vectordb",
            "cssa_app",
            "too-short",
        )

    mock_connect.assert_not_called()


def test_password_is_required_from_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("RUNTIME_DB_PASSWORD", raising=False)

    with pytest.raises(SystemExit) as error:
        provision.main(
            ["--database-url", "postgresql://admin:pw@db:5432/rag_vectordb"]
        )

    assert error.value.code == 2
    assert "RUNTIME_DB_PASSWORD" in capsys.readouterr().err


def test_provisioning_error_exits_non_zero(monkeypatch, capsys):
    monkeypatch.setenv("RUNTIME_DB_PASSWORD", "x" * 24)

    with patch.object(
        provision,
        "provision_runtime_role",
        side_effect=provision.ProvisioningError("tables do not exist yet"),
    ):
        exit_code = provision.main(
            ["--database-url", "postgresql://admin:pw@db:5432/rag_vectordb"]
        )

    assert exit_code == 1
    assert "tables do not exist yet" in capsys.readouterr().err


def test_success_prints_the_granted_privileges(monkeypatch, capsys):
    monkeypatch.setenv("RUNTIME_DB_PASSWORD", "x" * 24)
    result = provision.ProvisionResult(
        role="cssa_app",
        created=True,
        table_privileges={"knowledge_base": ("SELECT",)},
    )

    with patch.object(
        provision, "provision_runtime_role", return_value=result
    ) as mock_provision:
        exit_code = provision.main(
            [
                "--database-url",
                "postgresql://admin:pw@db:5432/rag_vectordb",
                "--role",
                "cssa_app",
            ]
        )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Runtime role cssa_app: created" in output
    assert "knowledge_base: SELECT" in output
    # The password arrives through the environment, never argv.
    mock_provision.assert_called_once_with(
        "postgresql://admin:pw@db:5432/rag_vectordb",
        "cssa_app",
        "x" * 24,
    )
