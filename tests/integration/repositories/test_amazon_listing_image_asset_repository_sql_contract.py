"""SQL contract tests for Amazon listing image asset repository."""

from src.repositories.amazon_listing_image_asset_repository import (
    AmazonListingImageAssetRepository,
)


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FetchResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class RecordingSession:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            raise AssertionError("Unexpected execute call")
        return self.results.pop(0)

    def commit(self):
        pass


def _normalized(sql):
    return " ".join(sql.split())


def test_upsert_asset_sql_contract():
    session = RecordingSession([ScalarResult(7)])
    repo = AmazonListingImageAssetRepository(session)

    asset_id = repo.upsert_asset(
        sku="MEOW1",
        vendor_sku="GIGA1",
        source_url="https://cdn.example/main.jpg",
        slot="main",
        review_status="auto_approved",
        content_type="image/jpeg",
        file_size_bytes=1000,
        inspection_result={"ok": True},
    )

    assert asset_id == 7
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "INSERT INTO product_image_assets" in sql
    assert "ON CONFLICT (sku, source_url)" in sql
    assert params["sku"] == "MEOW1"
    assert params["slot"] == "main"
    assert '"ok": true' in params["inspection_result"]


def test_get_assets_for_sku_sql_contract():
    session = RecordingSession([
        FetchResult([
            {
                "sku": "MEOW1",
                "source_url": "https://cdn.example/main.jpg",
                "review_status": "approved",
            }
        ])
    ])
    repo = AmazonListingImageAssetRepository(session)

    result = repo.get_assets_for_sku("MEOW1")

    assert result[0]["review_status"] == "approved"
    sql = _normalized(session.calls[0][0])
    assert "FROM product_image_assets" in sql
    assert "WHERE sku = :sku" in sql
    assert "ORDER BY" in sql
