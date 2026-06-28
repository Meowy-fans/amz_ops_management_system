import pytest
from unittest.mock import MagicMock, patch
from src.services.product_listing_service import ProductListingService


class FakeCommercialFinding:
    def __init__(self, code):
        self.code = code

    def as_dict(self):
        return {"code": self.code, "blocking": True}


class FakeCommercialResult:
    def __init__(self, blocked=False, codes=None, warning_codes=None, input_snapshot=None):
        self.blocked = blocked
        self.blocking_codes = codes or []
        self.warning_codes = warning_codes or []
        self.audit_run_id = 123
        self.input_snapshot = input_snapshot or {}
        self.findings = [FakeCommercialFinding(code) for code in self.blocking_codes]


class FakeCommercialGate:
    def __init__(self, blocked_skus=None):
        self.blocked_skus = set(blocked_skus or [])
        self.calls = []

    def evaluate(self, product_data, product_type):
        self.calls.append((product_data, product_type))
        sku = product_data.get("meow_sku")
        if sku in self.blocked_skus:
            return FakeCommercialResult(True, ["PRICE_STALE"])
        return FakeCommercialResult(False)


class FakeVariationResult:
    def __init__(
        self,
        decision="passed",
        parent_sku=None,
        variation_theme="Color",
        child_attributes=None,
        codes=None,
    ):
        self.mode = "append_child"
        self.decision = decision
        self.parent_sku = parent_sku
        self.variation_theme = variation_theme
        self.child_attributes = child_attributes or {}
        self.blocking_codes = codes or []
        self.warning_codes = []
        self.audit_run_id = 456
        self.findings = []


class FakeVariationResolver:
    def __init__(self, append_result=None, new_family_result=None):
        self.append_result = append_result
        self.new_family_result = new_family_result
        self.append_calls = []
        self.new_family_calls = []

    def resolve_append_child(self, **kwargs):
        self.append_calls.append(kwargs)
        return self.append_result

    def resolve_new_family(self, family_data, product_type):
        self.new_family_calls.append((family_data, product_type))
        if self.new_family_result is not None:
            return self.new_family_result
        return FakeVariationResult(
            decision="passed",
            parent_sku=None,
            variation_theme="Color",
            child_attributes={
                item["meow_sku"]: {"color_name": item["meow_sku"]}
                for item in family_data
            },
        )


class FakeSchemaService:
    def __init__(self, required_by_type=None):
        self.required_by_type = {
            key.upper(): value for key, value in (required_by_type or {}).items()
        }

    def get_required_properties(self, product_type):
        return self.required_by_type.get(str(product_type or "").upper(), [])

    def get_cached_valid_values(self, product_type, field_name):
        return None

    def get_valid_values(self, product_type, field_name):
        return None


@pytest.fixture
def mock_repo_context():
    """Mock all repositories and helpers"""
    # Note: VariationThemeService is imported inside __init__, so we can't patch it here easily via module attribute
    # We will handle it by mocking the module in sys.modules if needed, or just let it fail (it's optional in code)
    
    with patch('src.services.product_listing_service.ProductListingRepository') as MockListRepo, \
         patch('src.services.product_listing_service.ProductDataRepository') as MockDataRepo, \
         patch('src.services.product_listing_service.AmzTemplateRepository') as MockTemplRepo, \
         patch('src.services.product_listing_service.AmzListingLogRepository') as MockLogRepo, \
         patch('src.services.product_listing_service.DataMappingHelper') as MockMapper, \
         patch('src.services.product_listing_service.ExcelGenerator') as MockExcel, \
         patch('src.services.product_listing_service.VariationHelper') as MockVarHelper:
         
        yield {
            'list_repo': MockListRepo.return_value,
            'data_repo': MockDataRepo.return_value,
            'templ_repo': MockTemplRepo.return_value,
            'log_repo': MockLogRepo.return_value,
            'mapper': MockMapper.return_value,
            'excel': MockExcel.return_value,
            'var_helper': MockVarHelper.return_value
        }


def _api_product_data(**overrides):
    data = {
        'meow_sku': 'SKU1',
        'vendor_sku': 'GIGA1',
        'category_name': 'CABINET',
        'product_name': 'API Native Cabinet',
        'product_description': 'API native description.',
        'selling_point_1': 'Feature one',
        'raw_data': {'mainImageUrl': 'https://img.example/main.jpg'},
        'final_price': 199.99,
        'price_currency': 'USD',
        'cost_at_pricing': 100,
        'pricing_formula_version': 'v1',
        'price_updated_at': '2026-06-08T00:00:00+00:00',
        'inventory_quantity': 5,
        'buyer_qty': 99,
        'seller_qty': 0,
        'inventory_last_updated': '2026-06-08T00:00:00+00:00',
        'total_quantity': 5,
    }
    data.update(overrides)
    return data

@pytest.fixture
def service(mock_db_session, mock_repo_context):
    # Mock _load_category_config
    with patch.object(ProductListingService, '_load_category_config', return_value={}):
        svc = ProductListingService(mock_db_session)
        return svc

class TestProductListingService:
    def test_init(self, service):
        assert service.product_listing_repo is not None
        assert service.data_mapper is not None

    def test_generate_listings_no_pending_skus(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = []
        result = service.generate_listings_by_category("CABINET")
        assert result['success'] is False
        assert "没有待发品SKU" in result['message']

    def test_generate_listings_success_flow(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['templ_repo'].find_template_by_category.return_value = {'some': 'rules'}
        
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = {'meow_sku': 'SKU1'}
        mock_repo_context['mapper'].apply_mapping.return_value = {'Mapped': 'Data'}
        mock_repo_context['excel'].generate_excel.return_value = "/path/to/file.xlsm"
        
        result = service.generate_listings_by_category("CABINET")
        
        assert result['success'] is True
        assert result['excel_file'] == "/path/to/file.xlsm"
        
    def test_generate_listings_mapping_error_handled(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['templ_repo'].find_template_by_category.return_value = {'some': 'rules'}
        mock_repo_context['data_repo'].get_full_product_data.return_value = {'sk': 'u'}
        
        mock_repo_context['mapper'].apply_mapping.side_effect = Exception("Mapping Failed")
        
        result = service.generate_listings_by_category("CABINET")
        
        # 0 rows generated
        assert result['success'] is False
        assert "没有生成任何数据行" in result['message']

    def test_generate_listings_no_skus_for_category(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'MIRROR')]

        result = service.generate_listings_by_category("CABINET")

        assert result['success'] is False
        assert "没有待发品SKU" in result['message']
        mock_repo_context['list_repo'].get_variation_data.assert_not_called()

    def test_generate_listings_missing_template_rules(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['templ_repo'].find_template_by_category.return_value = None

        result = service.generate_listings_by_category("CABINET")

        assert result['success'] is False
        assert "没有模板规则" in result['message']
        mock_repo_context['data_repo'].get_full_product_data.assert_not_called()

    def test_generate_listings_rolls_back_on_excel_error(self, service, mock_repo_context, mock_db_session):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['templ_repo'].find_template_by_category.return_value = {'some': 'rules'}
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = {'meow_sku': 'SKU1'}
        mock_repo_context['mapper'].apply_mapping.return_value = {'Mapped': 'Data'}
        mock_repo_context['excel'].generate_excel.side_effect = RuntimeError("excel failed")

        result = service.generate_listings_by_category("CABINET")

        assert result['success'] is False
        assert "excel failed" in result['message']
        mock_db_session.rollback.assert_called_once()

    def test_process_single_family_generates_parent_child_rows_and_logs(self, service, mock_repo_context):
        service.variation_theme_service = MagicMock()
        service.variation_theme_service.determine_variation_theme.return_value = {
            'variation_theme': 'Color',
            'child_attributes': {
                'SKU1': {'color_name': 'White'},
                'SKU2': {'color_name': 'Black'}
            }
        }
        mock_repo_context['data_repo'].get_full_product_data.side_effect = [
            {'meow_sku': 'SKU1', 'name': 'Item White'},
            {'meow_sku': 'SKU2', 'name': 'Item Black'},
            {'meow_sku': 'SKU1', 'name': 'Item White'},
            {'meow_sku': 'SKU2', 'name': 'Item Black'}
        ]
        mock_repo_context['mapper'].apply_mapping.side_effect = [
            {'SKU': 'SKU1', 'Item Name': 'White Mirror'},
            {'SKU': 'SKU1'},
            {'SKU': 'SKU2'}
        ]
        mock_repo_context['var_helper'].generalize_parent_title.return_value = 'Mirror'
        template_rules = {
            'variation_mapping': {'color_name': 'Color'},
            'priority_themes': ['Color'],
            'valid_values': [{'attribute': 'Variation Theme Name', 'values': ['Color']}]
        }

        rows, logs = service._process_single_family(['SKU1', 'SKU2'], template_rules)

        assert len(rows) == 3
        assert rows[0]['Parentage Level'] == 'Parent'
        assert rows[0]['Item Name'] == 'Mirror'
        assert rows[1]['Parentage Level'] == 'Child'
        assert rows[1]['Color'] == 'White'
        assert rows[2]['Color'] == 'Black'
        assert len(logs) == 2
        assert logs[0]['status'] == 'GENERATED'

    def test_api_native_plan_generation_does_not_require_template_rules(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            raw_data={
                'mainImageUrl': 'https://img.example/main.jpg',
                'assembledLength': 30,
                'assembledWidth': 20,
                'assembledHeight': 34,
                'weight': 55,
                'attributes': {'Main Color': 'White'},
            },
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, variation_logs, single_skus, variation_families, pre_results = (
            service._build_api_native_plans_for_category('CABINET')
        )

        assert single_skus == ['SKU1']
        assert variation_families == []
        assert variation_logs == []
        assert pre_results == []
        assert plans[0]['sku'] == 'SKU1'
        assert plans[0]['attributes']['item_name'] == [{'value': 'API Native Cabinet'}]
        mock_repo_context['templ_repo'].find_template_by_category.assert_not_called()

    def test_api_native_plan_uses_commercial_gate_publish_quantity(
        self,
        service,
        mock_repo_context,
    ):
        class ClampingGate:
            def evaluate(self, product_data, product_type):
                return FakeCommercialResult(
                    blocked=False,
                    warning_codes=["PUBLISH_QUANTITY_CLAMPED"],
                    input_snapshot={
                        "source_publish_quantity": 50,
                        "publish_quantity": 10,
                    },
                )

        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            total_quantity=50,
            inventory_quantity=50,
            raw_data={
                'mainImageUrl': 'https://img.example/main.jpg',
                'assembledLength': 30,
                'assembledWidth': 20,
                'assembledHeight': 34,
            },
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = ClampingGate()

        plans, _logs, _single_skus, _families, pre_results = (
            service._build_api_native_plans_for_category('CABINET')
        )

        assert pre_results == []
        availability = plans[0]['attributes']['fulfillment_availability']
        assert availability[0]['quantity'] == 10

    def test_api_native_plan_generation_filters_explicit_sku_scope(
        self,
        service,
        mock_repo_context,
    ):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1', 'SKU2']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [
            ('SKU1', 'CABINET'),
        ]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            meow_sku='SKU1',
            vendor_sku='GIGA1',
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, _logs, single_skus, _families, pre_results = (
            service._build_api_native_plans_for_category(
                'CABINET',
                sku_list=['SKU1', 'SKU404'],
            )
        )

        assert [plan['sku'] for plan in plans] == ['SKU1']
        assert single_skus == ['SKU1']
        assert pre_results == [{
            'sku': 'SKU404',
            'status': 'blocked_scope_filter',
            'issues': 1,
            'blocking_codes': ['NOT_PENDING_OR_NOT_ELIGIBLE'],
            'message': 'SKU is not locally eligible for listing creation',
        }]
        mock_repo_context['list_repo'].get_variation_data.assert_called_once_with(['SKU1'])

    def test_generate_listings_via_api_filters_sku_file_and_reports_audit(
        self,
        service,
        mock_repo_context,
        tmp_path,
    ):
        sku_file = tmp_path / "cabinet-skus.txt"
        sku_file.write_text("SKU2\nSKU1\n", encoding="utf-8")
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1', 'SKU2']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [
            ('SKU2', 'CABINET'),
            ('SKU1', 'CABINET'),
        ]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU2', 'SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.side_effect = [
            _api_product_data(meow_sku='SKU2', vendor_sku='GIGA2'),
            _api_product_data(meow_sku='SKU1', vendor_sku='GIGA1'),
        ]
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        with patch('src.services.amazon_listing_submitter.AmazonListingSubmitter') as submitter_cls:
            submitter_cls.return_value.submit.return_value = [
                {'sku': 'SKU2', 'status': 'dry_run'},
                {'sku': 'SKU1', 'status': 'dry_run'},
            ]

            result = service.generate_listings_via_api(
                'CABINET',
                dry_run=True,
                sku_file=str(sku_file),
            )

        assert result['success'] is True
        assert result['audit']['scope']['requested_skus'] == ['SKU2', 'SKU1']
        assert result['audit']['result_status_counts'] == {'dry_run': 2}
        submitted_plans = submitter_cls.return_value.submit.call_args.args[0]
        assert [plan['sku'] for plan in submitted_plans] == ['SKU2', 'SKU1']

    def test_api_native_scope_only_not_on_amazon_skips_existing_sku(
        self,
        service,
        mock_repo_context,
    ):
        class ListingsClient:
            def __init__(self):
                self.calls = []

            def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
                from infrastructure.amazon.api_client import AmazonAPIException

                self.calls.append((sku, included_data))
                if sku == 'SKU1':
                    return {'body': {'sku': sku, 'status': 'DISCOVERABLE'}}
                raise AmazonAPIException("not found", status_code=404)

        client = ListingsClient()
        service._listings_client_instance = client
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1', 'SKU2']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [
            ('SKU1', 'CABINET'),
            ('SKU2', 'CABINET'),
        ]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU2'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            meow_sku='SKU2',
            vendor_sku='GIGA2',
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, _logs, single_skus, _families, pre_results = (
            service._build_api_native_plans_for_category(
                'CABINET',
                sku_list=['SKU1', 'SKU2'],
                only_not_on_amazon=True,
            )
        )

        assert [plan['sku'] for plan in plans] == ['SKU2']
        assert single_skus == ['SKU2']
        assert pre_results[0]['status'] == 'skipped_existing_scope'
        assert pre_results[0]['sku'] == 'SKU1'
        assert client.calls == [
            ('SKU1', ['summaries', 'issues', 'attributes', 'productTypes']),
            ('SKU2', ['summaries', 'issues', 'attributes', 'productTypes']),
        ]

    def test_generate_listings_via_api_uses_api_native_plans(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data()
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        with patch('src.utils.amazon_attribute_mapper.AmazonAttributeMapper') as mapper_cls, \
             patch('src.services.amazon_listing_submitter.AmazonListingSubmitter') as submitter_cls:
            submitter_cls.return_value.submit.return_value = [{'sku': 'SKU1', 'status': 'dry_run'}]

            result = service.generate_listings_via_api('CABINET', dry_run=True)

        assert result['success'] is True
        assert result['results'] == [{'sku': 'SKU1', 'status': 'dry_run'}]
        mapper_cls.assert_not_called()

    def test_generate_listings_via_api_blocks_v2_live(self, service):
        service.listing_payload_engine_mode = "v2"

        result = service.generate_listings_via_api("CABINET", dry_run=False)

        assert result == {
            "success": False,
            "results": [],
            "message": "v2_engine_requires_dry_run",
        }

    def test_api_native_plan_prefers_approved_image_assets(self, service, mock_repo_context):
        class Selector:
            def get_approved_images(self, sku):
                return type("Selected", (), {
                    "main_image_url": "https://cdn.example/approved-main.jpg",
                    "other_image_urls": ["https://cdn.example/approved-other.jpg"],
                })()

        service._image_selector_instance = Selector()
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            raw_data={
                'mainImageUrl': 'https://b2bfiles1.gigab2b.cn/raw-main.jpg',
                'imageUrls': ['https://b2bfiles1.gigab2b.cn/raw-other.jpg'],
            },
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, _logs, _single, _families, _pre = service._build_api_native_plans_for_category('CABINET')

        attrs = plans[0]['attributes']
        assert attrs['main_product_image_locator'] == [
            {'media_location': 'https://cdn.example/approved-main.jpg'}
        ]
        assert attrs['other_product_image_locator_1'] == [
            {'media_location': 'https://cdn.example/approved-other.jpg'}
        ]

    def test_api_native_plan_records_commercial_gate_block(self, service, mock_repo_context):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data()
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate(blocked_skus=['SKU1'])

        plans, _logs, _single, _families, pre_results = (
            service._build_api_native_plans_for_category('CABINET')
        )

        assert plans == []
        assert pre_results[0]['status'] == 'blocked_commercial_gate'
        assert pre_results[0]['blocking_codes'] == ['PRICE_STALE']

    def test_api_native_plan_blocks_missing_required_attribute_coverage(
        self,
        service,
        mock_repo_context,
    ):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [
            ('SKU1', 'TEST_MIRROR')
        ]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            category_name='TEST_MIRROR',
            raw_data={
                'mainImageUrl': 'https://img.example/main.jpg',
                'assembledLength': 30,
                'assembledWidth': 20,
                'assembledHeight': 34,
                'attributes': {'Main Color': 'Silver'},
            },
        )
        service._schema_service_instance = FakeSchemaService(
            {"TEST_MIRROR": ["item_name", "fabric_type"]}
        )
        service._commercial_gate_instance = FakeCommercialGate()

        plans, _logs, _single, _families, pre_results = (
            service._build_api_native_plans_for_category('TEST_MIRROR')
        )

        assert plans == []
        assert pre_results[0]['status'] == 'blocked_attribute_coverage'
        assert pre_results[0]['blocking_codes'] == ['MISSING_REQUIRED_ATTRIBUTE_RULE']
        assert pre_results[0]['missing_required'] == ['fabric_type']

    def test_api_native_plan_allows_home_mirror_fabric_type_fallback(
        self,
        service,
        mock_repo_context,
    ):
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [
            ('SKU1', 'HOME_MIRROR')
        ]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            category_name='HOME_MIRROR',
            raw_data={
                'mainImageUrl': 'https://img.example/main.jpg',
                'assembledLength': 30,
                'assembledWidth': 20,
                'assembledHeight': 34,
                'attributes': {'Main Color': 'Silver'},
            },
        )
        service._schema_service_instance = FakeSchemaService(
            {"HOME_MIRROR": ["item_name", "fabric_type"]}
        )
        service._commercial_gate_instance = FakeCommercialGate()

        plans, _logs, _single, _families, pre_results = (
            service._build_api_native_plans_for_category('HOME_MIRROR')
        )

        assert pre_results == []
        assert plans[0]['attributes']['fabric_type'] == [{"value": "Glass, Metal"}]

    def test_api_native_single_sku_appends_to_existing_parent_family(self, service, mock_repo_context):
        service._variation_resolver_instance = FakeVariationResolver(
            append_result=FakeVariationResult(
                parent_sku="PARENT-1",
                variation_theme="Color",
                child_attributes={"SKU1": {"color_name": "Blue"}},
            )
        )
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['list_repo'].get_meow_skus_by_vendor_skus.return_value = {
            "GIGA-A": "SKU-A",
            "GIGA-B": "SKU-B",
        }
        mock_repo_context['log_repo'].find_log_for_family.return_value = {
            "parent_sku": "PARENT-1",
            "status": "LISTED",
            "variation_theme": "Color",
        }
        mock_repo_context['log_repo'].get_family_details_by_parent.return_value = [
            {"meow_sku": "SKU-A", "variation_attributes": {"color_name": "White"}},
        ]
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            raw_data={
                'mainImageUrl': 'https://img.example/main.jpg',
                'associateProductList': ['GIGA-A', 'GIGA-B'],
                'attributes': {'Main Color': 'Blue'},
            },
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, logs, _single, _families, pre_results = (
            service._build_api_native_plans_for_category('CABINET')
        )

        attrs = plans[0]['attributes']
        assert pre_results == []
        assert logs == [{
            "meow_sku": "SKU1",
            "parent_sku": "PARENT-1",
            "variation_attributes": {"color_name": "Blue"},
            "listing_batch_id": None,
            "status": "GENERATED",
            "variation_theme": "Color",
        }]
        assert attrs['parentage_level'] == [{'value': 'child'}]
        assert attrs['variation_theme'] == [{'name': 'COLOR'}]
        assert attrs['child_parent_sku_relationship'][0]['parent_sku'] == 'PARENT-1'
        assert attrs['color'] == [{'value': 'Blue'}]

    def test_api_native_blocks_append_child_with_duplicate_variation_attributes(
        self,
        service,
        mock_repo_context,
    ):
        service._variation_resolver_instance = FakeVariationResolver(
            append_result=FakeVariationResult(
                decision="blocked",
                parent_sku="PARENT-1",
                variation_theme="Color",
                codes=["DUPLICATE_VARIATION_ATTRIBUTES"],
            )
        )
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [('SKU1', 'CABINET')]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['list_repo'].get_meow_skus_by_vendor_skus.return_value = {"GIGA-A": "SKU-A"}
        mock_repo_context['log_repo'].find_log_for_family.return_value = {
            "parent_sku": "PARENT-1",
            "status": "LISTED",
            "variation_theme": "Color",
        }
        mock_repo_context['log_repo'].get_family_details_by_parent.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = (['SKU1'], [])
        mock_repo_context['data_repo'].get_full_product_data.return_value = _api_product_data(
            raw_data={'associateProductList': ['GIGA-A']},
        )
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, logs, _single, _families, pre_results = (
            service._build_api_native_plans_for_category('CABINET')
        )

        assert plans == []
        assert logs == []
        assert pre_results[0]['status'] == 'blocked_variation_resolution'
        assert pre_results[0]['blocking_codes'] == ['DUPLICATE_VARIATION_ATTRIBUTES']

    def test_api_native_new_family_uses_variation_resolver_theme(self, service, mock_repo_context):
        service._variation_resolver_instance = FakeVariationResolver(
            new_family_result=FakeVariationResult(
                decision="passed",
                variation_theme="Color/Size",
                child_attributes={
                    "SKU1": {"color_name": "White", "size_name": "24"},
                    "SKU2": {"color_name": "Black", "size_name": "30"},
                },
            )
        )
        mock_repo_context['list_repo'].get_pending_listing_skus.return_value = ['SKU1', 'SKU2']
        mock_repo_context['list_repo'].get_sku_to_category_mapping.return_value = [
            ('SKU1', 'CABINET'),
            ('SKU2', 'CABINET'),
        ]
        mock_repo_context['list_repo'].get_variation_data.return_value = []
        mock_repo_context['var_helper'].find_variation_families.return_value = ([], [['SKU1', 'SKU2']])
        mock_repo_context['data_repo'].get_full_product_data.side_effect = [
            _api_product_data(meow_sku='SKU1', vendor_sku='GIGA1'),
            _api_product_data(meow_sku='SKU2', vendor_sku='GIGA2'),
        ]
        service._schema_service_instance = None
        service._commercial_gate_instance = FakeCommercialGate()

        plans, logs, _single, _families, pre_results = (
            service._build_api_native_plans_for_category('CABINET')
        )

        assert pre_results == []
        assert len(plans) == 3
        assert plans[0]['sku'].startswith('PARENT-')
        assert plans[0]['attributes']['variation_theme'] == [{'name': 'COLOR/ITEM_WIDTH'}]
        assert plans[0]['attributes']['fulfillment_availability'][0]['quantity'] == 0
        assert plans[1]['attributes']['color'] == [{'value': 'White'}]
        assert plans[1]['attributes']['item_width'] == [{'value': 24.0, 'unit': 'inches'}]
        assert logs[0]['variation_theme'] == 'Color/Size'
