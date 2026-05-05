from datetime import datetime

from src.cli.query_handlers import (
    handle_view_statistics,
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


class ErrorDb:
    def execute(self, query):
        raise RuntimeError("db down")


class Repo:
    def __init__(self, stats):
        self.stats = stats

    def get_statistics(self):
        if isinstance(self.stats, Exception):
            raise self.stats
        return self.stats


def test_handle_view_statistics_prints_all_repository_stats(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.repositories.amz_full_list_report_repository.AmzFullListReportRepository",
        lambda db: Repo({"total_records": 10, "active_listings": 8, "unique_asins": 6}),
    )
    monkeypatch.setattr(
        "src.repositories.giga_product_sync_repository.GigaProductSyncRepository",
        lambda db: Repo({"total_products": 20, "synced_products": 18, "oversized_products": 2}),
    )
    monkeypatch.setattr(
        "src.repositories.llm_product_detail_repository.LLMProductDetailRepository",
        lambda db: Repo({"total_details": 7, "unique_skus": 7}),
    )
    monkeypatch.setattr(
        "src.repositories.sku_mapping_repository.SkuMappingRepository",
        lambda db: Repo({"total_mappings": 5, "unique_vendors": 2}),
    )
    monkeypatch.setattr(
        "src.repositories.giga_product_price_repository.GigaProductPriceRepository",
        lambda db: Repo({"total_prices": 9, "available_skus": 8, "total_tiers": 3}),
    )
    monkeypatch.setattr(
        "src.repositories.giga_product_inventory_repository.GigaProductInventoryRepository",
        lambda db: Repo({"total_skus": 4, "in_stock_skus": 3, "total_quantity": 99}),
    )

    handle_view_statistics(db=object())

    output = capsys.readouterr().out
    assert "【Amazon数据】" in output
    assert "总记录: 10" in output
    assert "Active: 8" in output
    assert "唯一ASIN: 6" in output
    assert "【Giga商品】" in output
    assert "总记录: 20" in output
    assert "已同步: 18" in output
    assert "超大件: 2" in output
    assert "【LLM生成详情】" in output
    assert "唯一SKU: 7" in output
    assert "【SKU映射】" in output
    assert "供应商数: 2" in output
    assert "【Giga价格】" in output
    assert "价格梯度: 3" in output
    assert "【Giga库存】" in output
    assert "总库存量: 99" in output


def test_handle_view_statistics_prints_query_failures(monkeypatch, capsys):
    failing_repo = lambda db: Repo(RuntimeError("stats down"))
    monkeypatch.setattr(
        "src.repositories.amz_full_list_report_repository.AmzFullListReportRepository",
        failing_repo,
    )
    monkeypatch.setattr(
        "src.repositories.giga_product_sync_repository.GigaProductSyncRepository",
        failing_repo,
    )
    monkeypatch.setattr(
        "src.repositories.llm_product_detail_repository.LLMProductDetailRepository",
        failing_repo,
    )
    monkeypatch.setattr(
        "src.repositories.sku_mapping_repository.SkuMappingRepository",
        failing_repo,
    )
    monkeypatch.setattr(
        "src.repositories.giga_product_price_repository.GigaProductPriceRepository",
        failing_repo,
    )
    monkeypatch.setattr(
        "src.repositories.giga_product_inventory_repository.GigaProductInventoryRepository",
        failing_repo,
    )

    handle_view_statistics(db=object())

    assert capsys.readouterr().out.count("查询失败: stats down") == 6


def test_handle_pending_statistics_prints_counts(capsys):
    db = Db(Result(row=(10, 3, 2)))

    handle_pending_statistics(db)

    output = capsys.readouterr().out
    assert "总待发品数: 10" in output
    assert "CABINET: 3" in output
    assert "HOME_MIRROR: 2" in output
    assert "其他品类: 5" in output


def test_handle_pending_statistics_prints_errors(capsys):
    handle_pending_statistics(ErrorDb())

    assert "查询统计失败: db down" in capsys.readouterr().out


def test_handle_recent_listings_prints_rows(capsys):
    db = Db(Result(rows=[
        ("12345678-abcd", 4, 1, 3, "GENERATED", datetime(2026, 5, 4, 20, 0, 0))
    ]))

    handle_recent_listings(db)

    output = capsys.readouterr().out
    assert "批次 12345678" in output
    assert "SKU数: 4" in output
    assert "状态: GENERATED" in output


def test_handle_recent_listings_prints_na_for_missing_created_at(capsys):
    db = Db(Result(rows=[("12345678-abcd", 4, 1, 3, "GENERATED", None)]))

    handle_recent_listings(db)

    assert "时间: N/A" in capsys.readouterr().out


def test_handle_recent_listings_prints_empty_state(capsys):
    db = Db(Result(rows=[]))

    handle_recent_listings(db)

    assert "暂无发品记录" in capsys.readouterr().out


def test_handle_recent_listings_prints_errors(capsys):
    handle_recent_listings(ErrorDb())

    assert "查询记录失败: db down" in capsys.readouterr().out


def test_handle_list_categories_prints_categories(capsys):
    db = Db(Result(scalars=["CABINET", "HOME_MIRROR"]))

    handle_list_categories(db)

    output = capsys.readouterr().out
    assert "1. CABINET" in output
    assert "2. HOME_MIRROR" in output
    assert "总计: 2 个品类" in output


def test_handle_list_categories_prints_empty_state(capsys):
    db = Db(Result(scalars=[]))

    handle_list_categories(db)

    assert "暂无品类数据" in capsys.readouterr().out


def test_handle_list_categories_prints_errors(capsys):
    handle_list_categories(ErrorDb())

    assert "查询品类失败: db down" in capsys.readouterr().out
