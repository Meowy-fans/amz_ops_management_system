from infrastructure.amazon.api_client import AmazonAPIException
from src.services.product_listing_scope import ListingScope, ProductListingScopeFilter


class Repo:
    def __init__(self):
        self.pending = ["SKU1", "SKU2", "SKU3"]
        self.mapping = [
            ("SKU1", "CABINET"),
            ("SKU2", "HOME_MIRROR"),
            ("SKU3", "CABINET"),
        ]
        self.mapping_calls = []

    def get_pending_listing_skus(self):
        return self.pending

    def get_sku_to_category_mapping(self, skus):
        self.mapping_calls.append(skus)
        wanted = set(skus)
        return [item for item in self.mapping if item[0] in wanted]


class Client:
    def __init__(self, existing=None, error_skus=None):
        self.existing = set(existing or [])
        self.error_skus = set(error_skus or [])
        self.calls = []

    def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
        self.calls.append((sku, included_data))
        if sku in self.error_skus:
            raise AmazonAPIException("rate limited", status_code=429)
        if sku in self.existing:
            return {"body": {"sku": sku}}
        raise AmazonAPIException("not found", status_code=404)


def test_listing_scope_reads_file_dedupes_and_keeps_order(tmp_path):
    path = tmp_path / "skus.txt"
    path.write_text("SKU2\nSKU1, SKU2\n# comment\nSKU3\n", encoding="utf-8")

    scope = ListingScope.from_inputs(sku_list=["SKU1"], sku_file=str(path))

    assert scope.sku_list == ("SKU1", "SKU2", "SKU3")
    assert scope.as_dict()["requested_skus"] == ["SKU1", "SKU2", "SKU3"]


def test_scope_filter_records_category_mismatch_only_for_requested_scope():
    selection = ProductListingScopeFilter(Repo()).apply(
        "CABINET",
        ListingScope.from_inputs(sku_list=["SKU2", "SKU3"]),
    )

    assert selection.selected_skus == ["SKU3"]
    assert selection.pre_submit_results == [{
        "sku": "SKU2",
        "status": "blocked_scope_filter",
        "issues": 1,
        "blocking_codes": ["CATEGORY_MISMATCH_OR_UNMAPPED"],
        "message": "SKU is not mapped to category CABINET",
    }]


def test_scope_filter_only_not_on_amazon_skips_existing_and_keeps_missing():
    client = Client(existing=["SKU1"])
    selection = ProductListingScopeFilter(Repo(), listings_client=client).apply(
        "CABINET",
        ListingScope.from_inputs(
            sku_list=["SKU1", "SKU3"],
            only_not_on_amazon=True,
        ),
    )

    assert selection.selected_skus == ["SKU3"]
    assert selection.pre_submit_results[0]["status"] == "skipped_existing_scope"
    assert client.calls == [
        ("SKU1", ["summaries", "issues", "attributes", "productTypes"]),
        ("SKU3", ["summaries", "issues", "attributes", "productTypes"]),
    ]


def test_scope_filter_existing_check_errors_fail_closed():
    client = Client(error_skus=["SKU1"])
    selection = ProductListingScopeFilter(Repo(), listings_client=client).apply(
        "CABINET",
        ListingScope.from_inputs(
            sku_list=["SKU1", "SKU3"],
            only_not_on_amazon=True,
        ),
    )

    assert selection.selected_skus == ["SKU3"]
    assert selection.pre_submit_results[0]["status"] == "blocked_scope_filter"
    assert selection.pre_submit_results[0]["blocking_codes"] == [
        "EXISTING_LISTING_CHECK_FAILED"
    ]
