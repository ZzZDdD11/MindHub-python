from pathlib import Path

from sqlalchemy import create_engine, text

from app.infrastructure.database.migrations import MIGRATIONS_DIR, apply_pending_migrations


def test_default_migration_directory_contains_versioned_sql() -> None:
    assert (MIGRATIONS_DIR / "0001_schema_migrations.sql").is_file()
    assert (MIGRATIONS_DIR / "0002_request_log_stream_outcome.sql").is_file()


def test_applies_ordered_migrations_only_once(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0002_add_status.sql").write_text(
        "ALTER TABLE widgets ADD COLUMN status TEXT NOT NULL DEFAULT 'active';\n",
        encoding="utf-8",
    )
    (migrations_dir / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    engine = create_engine("sqlite://")

    with engine.begin() as connection:
        first_run = apply_pending_migrations(connection, migrations_dir)
        second_run = apply_pending_migrations(connection, migrations_dir)
        columns = connection.execute(text("PRAGMA table_info(widgets)")).mappings().all()
        applied = connection.execute(
            text("SELECT version FROM schema_migrations ORDER BY version")
        ).scalars().all()

    assert first_run == ["0001", "0002"]
    assert second_run == []
    assert [column["name"] for column in columns] == ["id", "status"]
    assert applied == ["0001", "0002"]


def test_rejects_duplicate_migration_versions(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_create_widgets.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (migrations_dir / "0001_add_status.sql").write_text("SELECT 1;\n", encoding="utf-8")
    engine = create_engine("sqlite://")

    with engine.begin() as connection:
        try:
            apply_pending_migrations(connection, migrations_dir)
        except ValueError as error:
            assert "Duplicate migration version: 0001" in str(error)
        else:
            raise AssertionError("Expected duplicate migration versions to be rejected")
