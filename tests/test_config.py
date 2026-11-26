from src.config import get_database_config


def test_database_config_defaults_to_local_docker_compose(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    assert get_database_config() == {
        "host": "localhost",
        "port": 5432,
        "dbname": "job_pipeline",
        "user": "job_user",
        "password": "job_password",
    }


def test_database_config_environment_overrides_defaults(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example.test")
    monkeypatch.setenv("POSTGRES_PORT", "15432")
    monkeypatch.setenv("POSTGRES_DB", "custom_db")
    monkeypatch.setenv("POSTGRES_USER", "custom_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "custom_password")

    assert get_database_config() == {
        "host": "db.example.test",
        "port": 15432,
        "dbname": "custom_db",
        "user": "custom_user",
        "password": "custom_password",
    }
