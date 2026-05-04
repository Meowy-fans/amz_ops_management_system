import pytest
from unittest.mock import MagicMock, call, patch
import sys
from src.services.product_listing_service import ProductListingService

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
