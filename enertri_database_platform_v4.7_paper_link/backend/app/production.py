"""Fail closed on unsafe production configuration; never print secret values."""
import os


def is_production():
    return os.getenv("APP_ENV", "development").lower() in {"production", "prod"}


def validate_production():
    if not is_production():
        return
    errors = []
    secret = os.getenv("SECRET_KEY", "")
    if len(secret) < 32 or any(x in secret.lower() for x in ("change", "example", "replace", "dev-secret")):
        errors.append("SECRET_KEY must be a random secret of at least 32 characters")
    if not os.getenv("DATABASE_URL", "").startswith(("postgresql", "postgres://")):
        errors.append("Production requires PostgreSQL")
    if os.getenv("APP_BOOTSTRAP_ON_STARTUP", "false").lower() != "false":
        errors.append("Run the one-shot bootstrap service instead of API startup seeding")
    if os.getenv("TASK_EXECUTION_MODE") != "database_worker":
        errors.append("Production requires database_worker")
    if errors:
        raise RuntimeError("; ".join(errors))
