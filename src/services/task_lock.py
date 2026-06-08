"""Database-backed task locks for scheduled jobs."""

import hashlib
from typing import Optional

from sqlalchemy import text


class PostgresAdvisoryLock:
    """Small wrapper around PostgreSQL session-level advisory locks."""

    def __init__(self, db, lock_name: str):
        self.db = db
        self.lock_name = lock_name
        self.lock_id = self._lock_id(lock_name)
        self.acquired = False

    def acquire(self) -> bool:
        result = self.db.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": self.lock_id},
        ).scalar()
        self.acquired = bool(result)
        return self.acquired

    def release(self) -> Optional[bool]:
        if not self.acquired:
            return None
        result = self.db.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": self.lock_id},
        ).scalar()
        self.acquired = False
        return bool(result)

    @staticmethod
    def _lock_id(lock_name: str) -> int:
        raw = hashlib.sha256(lock_name.encode("utf-8")).digest()[:8]
        value = int.from_bytes(raw, byteorder="big", signed=False)
        if value >= 2**63:
            value -= 2**64
        return value
