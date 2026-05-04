from datetime import datetime

from src.cli.query_handlers import (
    handle_list_categories,
    handle_pending_statistics,
    handle_recent_listings,
)


class Result:
    def __init__(self, row=None, rows=None, scalars=None):
        self._row = row
        self._rows = rows or []
        self._scalars = scalars or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def scalars(self):
        return self

    def all(self):
        return self._scalars


class Db:
    def __init__(self, result):
        self.result = result
        self.queries = []

    def execute(self, query):
        self.queries.append(query)
        return self.result


def test_handle_pending_statistics_prints_counts(capsys):
    db = Db(Result(row=(10, 3, 2)))

    handle_pending_statistics(db)

    output = capsys.readouterr().out
    assert "总待发品数: 10" in output
    assert "CABINET: 3" in output
    assert "HOME_MIRROR: 2" in output
    assert "其他品类: 5" in output


def test_handle_recent_listings_prints_rows(capsys):
    db = Db(Result(rows=[
        ("12345678-abcd", 4, 1, 3, "GENERATED", datetime(2026, 5, 4, 20, 0, 0))
    ]))

    handle_recent_listings(db)

    output = capsys.readouterr().out
    assert "批次 12345678" in output
    assert "SKU数: 4" in output
    assert "状态: GENERATED" in output


def test_handle_list_categories_prints_categories(capsys):
    db = Db(Result(scalars=["CABINET", "HOME_MIRROR"]))

    handle_list_categories(db)

    output = capsys.readouterr().out
    assert "1. CABINET" in output
    assert "2. HOME_MIRROR" in output
    assert "总计: 2 个品类" in output
