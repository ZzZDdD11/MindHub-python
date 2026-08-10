"""Run pending database migrations with: python -m app.infrastructure.database."""
from app.infrastructure.database.connection import engine
from app.infrastructure.database.migrations import apply_pending_migrations


def main() -> None:
    with engine.begin() as connection:
        applied = apply_pending_migrations(connection)
    print("Applied migrations: " + (", ".join(applied) if applied else "none"))


if __name__ == "__main__":
    main()
