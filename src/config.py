import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)


def get_database_config() -> dict:
    config = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.getenv("POSTGRES_DB", "job_pipeline"),
        "user": os.getenv("POSTGRES_USER", "job_user"),
        "password": os.getenv("POSTGRES_PASSWORD", "job_password"),
    }
    application_name = os.getenv("PGAPPNAME")
    if application_name:
        config["application_name"] = application_name
    return config


BA_API_KEY = os.getenv("BA_API_KEY", "jobboerse-jobsuche")
