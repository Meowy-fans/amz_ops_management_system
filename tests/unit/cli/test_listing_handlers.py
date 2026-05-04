from src.cli.listing_handlers import handle_generate_listing


def test_generate_listing_invalid_interactive_choice(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "9")

    result = handle_generate_listing(db=object())

    output = capsys.readouterr().out
    assert result is None
    assert "无效的选择" in output


def test_generate_listing_success_prints_result(monkeypatch, capsys):
    class Service:
        def __init__(self, db):
            self.db = db

        def generate_listings_by_category(self, category):
            return {
                "success": True,
                "batch_id": "batch-1",
                "excel_file": "output/file.xlsm",
                "single_count": 1,
                "variation_count": 2,
                "total_rows": 3,
                "message": "ok",
            }

    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing(db=object(), category="CABINET")

    output = capsys.readouterr().out
    assert result["success"] is True
    assert "发品文件生成成功" in output
    assert "output/file.xlsm" in output
