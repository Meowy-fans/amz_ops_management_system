from src.cli.listing_handlers import handle_generate_listing


class ListingService:
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


class FailingListingService:
    def __init__(self, db):
        self.db = db

    def generate_listings_by_category(self, category):
        return {
            "success": False,
            "message": f"no pending listings for {category}",
        }


class ErrorListingService:
    def __init__(self, db):
        self.db = db

    def generate_listings_by_category(self, category):
        raise RuntimeError(f"boom for {category}")


def test_generate_listing_returns_to_menu(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")

    result = handle_generate_listing(db=object())

    assert result is None


def test_generate_listing_invalid_interactive_choice(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "9")

    result = handle_generate_listing(db=object())

    output = capsys.readouterr().out
    assert result is None
    assert "无效的选择" in output


def test_generate_listing_success_prints_result(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.cli.listing_handlers.ProductListingService",
        ListingService,
    )

    result = handle_generate_listing(db=object(), category="CABINET")

    output = capsys.readouterr().out
    assert result["success"] is True
    assert "发品文件生成成功" in output
    assert "output/file.xlsm" in output


def test_generate_listing_interactive_choice_runs_selected_category(monkeypatch):
    seen = []

    class Service(ListingService):
        def generate_listings_by_category(self, category):
            seen.append(category)
            return super().generate_listings_by_category(category)

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing(db=object())

    assert result["success"] is True
    assert seen == ["CABINET"]


def test_generate_listing_failure_prints_reason(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.cli.listing_handlers.ProductListingService",
        FailingListingService,
    )

    result = handle_generate_listing(db=object(), category="HOME_MIRROR")

    output = capsys.readouterr().out
    assert result["success"] is False
    assert "发品文件生成失败" in output
    assert "no pending listings for HOME_MIRROR" in output


def test_generate_listing_prints_system_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.cli.listing_handlers.ProductListingService",
        ErrorListingService,
    )

    result = handle_generate_listing(db=object(), category="CABINET")

    output = capsys.readouterr().out
    assert result is None
    assert "系统错误" in output
    assert "boom for CABINET" in output
