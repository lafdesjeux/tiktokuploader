from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from .config import APP_AUTHOR, APP_NAME


class PublishQueue:
    def __init__(self, database_path: Path | None = None) -> None:
        if database_path is None:
            data_dir = Path(user_data_dir(APP_NAME, APP_AUTHOR))
            data_dir.mkdir(parents=True, exist_ok=True)
            database_path = data_dir / "publish_queue.sqlite3"
        self.database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    publish_id TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def add(self, scheduled_at: datetime, payload: dict[str, Any]) -> int:
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO jobs(scheduled_at, created_at, status, payload) VALUES (?, ?, 'scheduled', ?)",
                (scheduled_at.astimezone(timezone.utc).isoformat(), now, json.dumps(payload, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def list(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY scheduled_at ASC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(row) for row in rows]

    def due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('scheduled', 'retry') AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
                """,
                (now.astimezone(timezone.utc).isoformat(),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def update(
        self,
        job_id: int,
        *,
        status: str,
        publish_id: str = "",
        last_error: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status=?, publish_id=?, last_error=? WHERE id=?",
                (status, publish_id, last_error, job_id),
            )

    def delete(self, job_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        return value
