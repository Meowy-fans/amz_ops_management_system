from src.services.task_lock import PostgresAdvisoryLock


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeDb:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return ScalarResult(self.values.pop(0))


def test_postgres_advisory_lock_acquire_and_release():
    db = FakeDb([True, True])
    lock = PostgresAdvisoryLock(db, "amazon_price_inventory_update")

    assert lock.acquire() is True
    assert lock.acquired is True
    assert lock.release() is True
    assert lock.acquired is False
    assert "pg_try_advisory_lock" in db.calls[0][0]
    assert "pg_advisory_unlock" in db.calls[1][0]
    assert db.calls[0][1]["lock_id"] == db.calls[1][1]["lock_id"]


def test_postgres_advisory_lock_release_without_acquire_is_noop():
    db = FakeDb([])
    lock = PostgresAdvisoryLock(db, "amazon_price_inventory_update")

    assert lock.release() is None
    assert db.calls == []


def test_postgres_advisory_lock_reports_busy_lock():
    db = FakeDb([False])
    lock = PostgresAdvisoryLock(db, "amazon_price_inventory_update")

    assert lock.acquire() is False
    assert lock.acquired is False
