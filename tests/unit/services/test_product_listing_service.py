import pytest
from unittest.mock import MagicMock, call, patch
import sys
from src.services.product_listing_service import ProductListingService


class FakeCommercialFinding:
    def __init__(self, code):
        self.code = code

    def as_dict(self):
        return {"code": self.code, "blocking": True}


class FakeCommercialResult:
    def __init__(self, blocked=False, codes=None):
        self.blocked = blocked
        self.blocking_codes = codes or []
        self.warning_codes = []
        self.audit_run_id = 123
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
        assert attrs['variation_theme'] == [{'name': 'Color'}]
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
        assert plans[0]['attributes']['variation_theme'] == [{'name': 'Color/Size'}]
        assert plans[1]['attributes']['color'] == [{'value': 'White'}]
        assert plans[1]['attributes']['size_name'] == [{'value': '24'}]
        assert logs[0]['variation_theme'] == 'Color/Size'
