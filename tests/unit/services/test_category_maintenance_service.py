import pytest
import os
import io
from unittest.mock import MagicMock, patch, mock_open
from sqlalchemy.orm import Session
from src.services.category_maintenance_service import CategoryMaintenanceService
from src.services.progress_reporter import NullProgressReporter

class TestCategoryMaintenanceService:
    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_repo(self):
        with patch('src.services.category_maintenance_service.CategoryRepository') as MockRepo:
            yield MockRepo.return_value

    @pytest.fixture
    def service(self, mock_db, mock_repo):
        return CategoryMaintenanceService(mock_db)

    def test_sync_giga_categories_new_mappings(self, service, mock_repo):
        # 1. Mock Giga categories
        mock_repo.get_giga_category_codes.return_value = [
            {'category_code': 'C1', 'category_name': 'Cat 1'},
            {'category_code': 'C2', 'category_name': 'Cat 2'}
        ]
        
        # 2. Mock existing mappings (only C1 exists)
        mock_repo.get_existing_category_codes.return_value = ['C1']
        
        # 3. Mock insert return count
        mock_repo.batch_insert_category_mappings.return_value = 1

        result = service.sync_giga_categories()

        assert result['total_giga_categories'] == 2
        assert result['existing_mappings'] == 1
        assert result['new_categories'] == 1
        assert result['inserted_count'] == 1
        
        # Verify call args
        call_args = mock_repo.batch_insert_category_mappings.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]['supplier_category_code'] == 'C2'
        assert call_args[0]['supplier_platform'] == 'giga'

    def test_sync_giga_categories_no_new(self, service, mock_repo):
        mock_repo.get_giga_category_codes.return_value = [{'category_code': 'C1', 'category_name': 'Cat 1'}]
        mock_repo.get_existing_category_codes.return_value = ['C1']
        
        result = service.sync_giga_categories()
        
        assert result['new_categories'] == 0
        mock_repo.batch_insert_category_mappings.assert_not_called()

    def test_update_mappings_from_csv_success(self, service, mock_repo):
        csv_content = (
            "supplier_platform,supplier_category_code,standard_category_name\n"
            "giga,C1,HOME_DECOR\n"
            "giga,C2,FURNITURE"
        )
        
        # Mock file existence
        with patch('os.path.exists', return_value=True):
            # Mock file opening
            with patch('builtins.open', mock_open(read_data=csv_content)):
                # Mock repository validation
                mock_repo.get_valid_amazon_categories.return_value = {'home_decor', 'furniture'}
                
                # Mock update count
                mock_repo.batch_update_category_mappings.return_value = 2
                
                result = service.update_mappings_from_csv("dummy.csv")
                
                assert result['total_rows'] == 2
                assert result['valid_rows'] == 2
                assert result['updated_count'] == 2
                assert len(result['errors']) == 0

    def test_update_mappings_from_csv_validation_error(self, service, mock_repo):
        csv_content = (
            "supplier_platform,supplier_category_code,standard_category_name\n"
            "giga,C1,INVALID_CAT\n"
            ",C2,VALID_CAT" # Missing platform
        )
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=csv_content)):
                mock_repo.get_valid_amazon_categories.return_value = {'valid_cat'}
                
                result = service.update_mappings_from_csv("dummy.csv")
                
                assert result['total_rows'] == 2
                assert result['valid_rows'] == 0
                assert result['invalid_rows'] == 2
                # Expect 2 errors: 1 invalid cat, 1 missing field
                assert len(result['errors']) == 2

    def test_sync_giga_categories_with_null_reporter_does_not_print(
        self,
        mock_db,
        mock_repo,
        capsys
    ):
        service = CategoryMaintenanceService(mock_db, reporter=NullProgressReporter())
        service.repository = mock_repo
        mock_repo.get_giga_category_codes.return_value = []

        result = service.sync_giga_categories()

        assert result['total_giga_categories'] == 0
        assert capsys.readouterr().out == ""

    def test_update_mappings_from_csv_with_null_reporter_does_not_print(
        self,
        mock_db,
        mock_repo,
        capsys
    ):
        service = CategoryMaintenanceService(mock_db, reporter=NullProgressReporter())
        service.repository = mock_repo

        with patch('os.path.exists', return_value=False):
            result = service.update_mappings_from_csv("missing.csv")

        assert result['errors'] == ["文件不存在: missing.csv"]
        assert capsys.readouterr().out == ""
