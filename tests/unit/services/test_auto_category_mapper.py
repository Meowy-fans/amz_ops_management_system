from src.services.auto_category_mapper import AutoCategoryMapper


class FakeRepository:
    def __init__(self, samples=None, unmapped=None):
        self.samples = samples or [
            {
                "giga_sku": "GIGA-1",
                "name": "Modern Sofa With Chaise for Living Room",
                "category_name": "Sofas",
            },
            {
                "giga_sku": "GIGA-2",
                "name": "Convertible Sofa Bed",
                "category_name": "Sofas",
            },
        ]
        self.unmapped = unmapped or [
            {"category_code": "10027", "category_name": "Sofas", "product_count": 8}
        ]
        self.updates = []

    def get_category_sample_products(self, category_code, limit=5):
        return self.samples[:limit]

    def get_unmapped_categories_with_product_count(self, platform="giga"):
        return self.unmapped

    def batch_update_category_mappings(self, updates):
        self.updates.extend(updates)
        return len(updates)


class FakeCatalogClient:
    def __init__(self, asins=None, summaries=None):
        self.asins = ["ASIN1", "ASIN2", "ASIN3", "ASIN4"] if asins is None else asins
        self.summaries = summaries or {
            "ASIN1": {"product_type": "SOFA"},
            "ASIN2": {"product_type": "SOFA"},
            "ASIN3": {"product_type": "SOFA"},
            "ASIN4": {"product_type": "CHAIR"},
        }
        self.search_calls = []
        self.summary_calls = []

    def search_catalog_items(self, keywords=None):
        self.search_calls.append(keywords)
        return {"body": {"items": [{"asin": asin} for asin in self.asins]}}

    def batch_get_summaries(self, asins):
        self.summary_calls.append(asins)
        return {asin: self.summaries[asin] for asin in asins if asin in self.summaries}


class FakeProductTypeClient:
    def __init__(self, candidates=None):
        self.candidates = candidates or ["SOFA", "FURNITURE"]
        self.calls = []

    def search_product_types(self, keywords):
        self.calls.append(keywords)
        return self.candidates


class FakeSchemaService:
    def __init__(self, fail=False):
        self.fail = fail
        self.cached = []

    def fetch_and_cache(self, product_type):
        if self.fail:
            raise RuntimeError("schema unavailable")
        self.cached.append(product_type)
        return {"schema_json": {}, "required_properties": []}


def test_auto_category_mapper_votes_catalog_product_type_and_writes_when_not_dry_run():
    repository = FakeRepository()
    schema_service = FakeSchemaService()
    mapper = AutoCategoryMapper(
        db=object(),
        repository=repository,
        catalog_client=FakeCatalogClient(),
        product_type_client=FakeProductTypeClient(candidates=["SOFA"]),
        schema_service=schema_service,
    )

    result = mapper.discover_category("10027", dry_run=False)

    assert result.status == "mapped"
    assert result.selected_product_type == "SOFA"
    assert result.vote_counts == {"SOFA": 3, "CHAIR": 1}
    assert result.written is True
    assert repository.updates == [
        {
            "supplier_platform": "giga",
            "supplier_category_code": "10027",
            "standard_category_name": "SOFA",
        }
    ]
    assert schema_service.cached == ["SOFA"]


def test_auto_category_mapper_dry_run_does_not_write_or_cache_schema():
    repository = FakeRepository()
    schema_service = FakeSchemaService()
    mapper = AutoCategoryMapper(
        db=object(),
        repository=repository,
        catalog_client=FakeCatalogClient(),
        product_type_client=FakeProductTypeClient(candidates=["SOFA"]),
        schema_service=schema_service,
    )

    result = mapper.discover_category("10027", dry_run=True)

    assert result.status == "dry_run_selected"
    assert result.selected_product_type == "SOFA"
    assert result.written is False
    assert repository.updates == []
    assert schema_service.cached == []


def test_auto_category_mapper_marks_low_confidence_when_votes_are_split():
    mapper = AutoCategoryMapper(
        db=object(),
        repository=FakeRepository(),
        catalog_client=FakeCatalogClient(
            summaries={
                "ASIN1": {"product_type": "SOFA"},
                "ASIN2": {"product_type": "CHAIR"},
                "ASIN3": {"product_type": "BENCH"},
                "ASIN4": {"product_type": "OTTOMAN"},
            }
        ),
        product_type_client=FakeProductTypeClient(candidates=["SOFA", "CHAIR"]),
        schema_service=FakeSchemaService(),
    )

    result = mapper.discover_category("10027", dry_run=False)

    assert result.status == "needs_review"
    assert result.selected_product_type is None
    assert result.written is False
    assert "Catalog vote confidence below threshold" in result.warnings


def test_auto_category_mapper_falls_back_to_product_type_search_when_catalog_has_no_votes():
    mapper = AutoCategoryMapper(
        db=object(),
        repository=FakeRepository(),
        catalog_client=FakeCatalogClient(asins=[], summaries={}),
        product_type_client=FakeProductTypeClient(candidates=["SOFA", "FURNITURE"]),
        schema_service=FakeSchemaService(),
    )

    result = mapper.discover_category("10027", dry_run=False)

    assert result.status == "needs_review"
    assert result.selected_product_type is None
    assert result.fallback_candidates == ["SOFA", "FURNITURE"]
    assert "Catalog search returned no usable product types" in result.warnings


def test_auto_category_mapper_discovers_all_unmapped_categories():
    repository = FakeRepository(
        unmapped=[
            {"category_code": "10027", "category_name": "Sofas", "product_count": 8},
            {"category_code": "10028", "category_name": "Chairs", "product_count": 4},
        ]
    )
    mapper = AutoCategoryMapper(
        db=object(),
        repository=repository,
        catalog_client=FakeCatalogClient(),
        product_type_client=FakeProductTypeClient(candidates=["SOFA"]),
        schema_service=FakeSchemaService(),
    )

    results = mapper.discover_unmapped(dry_run=True)

    assert [result.category_code for result in results] == ["10027", "10028"]
