"""Small, ordered SQL migration runner for the WaLiAPI database."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^(\d+)_[A-Za-z0-9][A-Za-z0-9_-]*\.sql$")


def _migration_files(migrations_dir: Path) -> Iterable[tuple[str, Path]]:
    migrations: list[tuple[str, Path]] = []
    versions: set[str] = set()
    for path in migrations_dir.glob("*.sql"):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if not match:
            raise ValueError(f"Invalid migration filename: {path.name}")
        version = match.group(1)
        if version in versions:
            raise ValueError(f"Duplicate migration version: {version}")
        versions.add(version)
        migrations.append((version, path))
    return sorted(migrations, key=lambda item: item[0])


def _statements(sql: str) -> Iterable[str]:
    for statement in sql.split(";"):
        lines = [line for line in statement.splitlines() if not line.lstrip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            yield statement


def apply_pending_migrations(connection: Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply each numbered SQL migration once within the caller's transaction."""
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version VARCHAR(64) PRIMARY KEY, "
        "filename VARCHAR(255) NOT NULL, "
        "applied_at VARCHAR(32) NOT NULL)"
    ))
    applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    executed: list[str] = []

    for version, path in _migration_files(migrations_dir):
        if version in applied:
            continue
        for statement in _statements(path.read_text(encoding="utf-8")):
            connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO schema_migrations (version, filename, applied_at) "
                "VALUES (:version, :filename, :applied_at)"
            ),
            {
                "version": version,
                "filename": path.name,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        executed.append(version)

    return executed
