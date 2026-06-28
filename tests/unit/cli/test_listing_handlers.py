from src.cli.listing_handlers import handle_generate_listing, handle_generate_listing_api


class ListingService:
    def __init__(self, db):
        self.db = db

    def generate_listings_via_api(
        self,
        category_name,
        dry_run=True,
        validation_only=False,
        sku_list=None,
        sku_file=None,
        only_not_on_amazon=False,
    ):
        return {
            "success": True,
            "results": [{"sku": "meow1", "status": "dry_run"}],
            "dry_run": dry_run,
            "category": category_name,
            "validation_only": validation_only,
            "sku_list": sku_list,
            "sku_file": sku_file,
            "only_not_on_amazon": only_not_on_amazon,
        }


class FailingListingService:
    def __init__(self, db):
        self.db = db

    def generate_listings_via_api(
        self,
        category_name,
        dry_run=True,
        validation_only=False,
        sku_list=None,
        sku_file=None,
        only_not_on_amazon=False,
    ):
        return {
            "success": False,
            "message": f"no pending listings for {category_name}",
        }


class ErrorListingService:
    def __init__(self, db):
        self.db = db

    def generate_listings_via_api(
        self,
        category_name,
        dry_run=True,
        validation_only=False,
        sku_list=None,
        sku_file=None,
        only_not_on_amazon=False,
    ):
        raise RuntimeError(f"boom for {category_name}")


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
    assert "DEPRECATED" in output
    assert "Amazon SP-API 新品发品" in output
    assert "发品API完成" in output


def test_generate_listing_interactive_choice_runs_selected_category(monkeypatch):
    seen = []

    class Service(ListingService):
        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            seen.append((category_name, validation_only))
            return super().generate_listings_via_api(
                category_name,
                dry_run=dry_run,
                validation_only=validation_only,
                sku_list=sku_list,
                sku_file=sku_file,
                only_not_on_amazon=only_not_on_amazon,
            )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing(db=object())

    assert result["success"] is True
    assert seen == [("CABINET", False)]


def test_generate_listing_api_strict_validation_passes_validation_only(monkeypatch, capsys):
    seen = []

    class Service(ListingService):
        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            seen.append((category_name, dry_run, validation_only))
            return super().generate_listings_via_api(
                category_name,
                dry_run=dry_run,
                validation_only=validation_only,
                sku_list=sku_list,
                sku_file=sku_file,
                only_not_on_amazon=only_not_on_amazon,
            )

    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=True,
        strict_validation=True,
    )

    output = capsys.readouterr().out
    assert result["success"] is True
    assert "STRICT DRY RUN" in output
    assert seen == [("CABINET", True, True)]


def test_generate_listing_api_passes_sku_scope(monkeypatch):
    seen = []

    class Service(ListingService):
        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            seen.append({
                "category_name": category_name,
                "dry_run": dry_run,
                "validation_only": validation_only,
                "sku_list": sku_list,
                "sku_file": sku_file,
                "only_not_on_amazon": only_not_on_amazon,
            })
            return super().generate_listings_via_api(
                category_name,
                dry_run=dry_run,
                validation_only=validation_only,
                sku_list=sku_list,
                sku_file=sku_file,
                only_not_on_amazon=only_not_on_amazon,
            )

    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=True,
        strict_validation=True,
        sku_list=["SKU1", "SKU2"],
        sku_file="/tmp/skus.txt",
        only_not_on_amazon=True,
    )

    assert result["success"] is True
    assert seen == [{
        "category_name": "CABINET",
        "dry_run": True,
        "validation_only": True,
        "sku_list": ["SKU1", "SKU2"],
        "sku_file": "/tmp/skus.txt",
        "only_not_on_amazon": True,
    }]


def test_generate_listing_api_shadow_sets_service_engine(monkeypatch, capsys):
    seen = []

    class Service(ListingService):
        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            seen.append(getattr(self, "listing_payload_engine_mode", None))
            return super().generate_listings_via_api(
                category_name,
                dry_run=dry_run,
                validation_only=validation_only,
                sku_list=sku_list,
                sku_file=sku_file,
                only_not_on_amazon=only_not_on_amazon,
            )

    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=True,
        engine="shadow",
    )

    output = capsys.readouterr().out
    assert result["success"] is True
    assert seen == ["shadow"]
    assert "Listing payload engine: shadow" in output


def test_generate_listing_api_rejects_strict_validation_with_live(capsys):
    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=False,
        strict_validation=True,
    )

    capsys.readouterr()
    assert result["success"] is False
    assert result["message"] == "strict_validation_requires_dry_run"


def test_generate_listing_api_rejects_shadow_with_live(capsys):
    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=False,
        engine="shadow",
    )

    output = capsys.readouterr().out
    assert result["success"] is False
    assert result["message"] == "shadow_engine_requires_dry_run"
    assert "shadow engine" in output


def test_generate_listing_api_allows_v2_dry_run(monkeypatch, capsys):
    seen = []

    class Service(ListingService):
        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            seen.append(self.listing_payload_engine_mode)
            return super().generate_listings_via_api(
                category_name,
                dry_run=dry_run,
                validation_only=validation_only,
                sku_list=sku_list,
                sku_file=sku_file,
                only_not_on_amazon=only_not_on_amazon,
            )

    monkeypatch.setattr("src.cli.listing_handlers.ProductListingService", Service)

    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=True,
        engine="v2",
    )

    output = capsys.readouterr().out
    assert result["success"] is True
    assert seen == ["v2"]
    assert "Listing payload engine: v2 authoritative dry-run canary" in output


def test_generate_listing_api_rejects_v2_live(capsys):
    result = handle_generate_listing_api(
        db=object(),
        category="CABINET",
        dry_run=False,
        engine="v2",
    )

    output = capsys.readouterr().out
    assert result["success"] is False
    assert result["message"] == "v2_engine_requires_dry_run"
    assert "只允许 dry-run" in output


def test_generate_listing_failure_prints_reason(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.cli.listing_handlers.ProductListingService",
        FailingListingService,
    )

    result = handle_generate_listing(db=object(), category="HOME_MIRROR")

    output = capsys.readouterr().out
    assert result["success"] is False
    assert "失败" in output
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
