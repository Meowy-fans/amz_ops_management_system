import pytest
from unittest.mock import MagicMock, ANY
from sqlalchemy import text
from src.repositories.product_listing_repository import ProductListingRepository

@pytest.fixture
def mock_db_session():
    return MagicMock()

@pytest.fixture
def repo(mock_db_session):
    return ProductListingRepository(mock_db_session)

class TestProductListingRepository:
    def test_get_pending_listing_skus(self, repo, mock_db_session):
        # Setup mock result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ['SKU1', 'SKU2']
        mock_db_session.execute.return_value = mock_result
        
        skus = repo.get_pending_listing_skus()
        
        assert skus == ['SKU1', 'SKU2']
        # Verify execute called
        mock_db_session.execute.assert_called_once()
        # Verify SQL contains expected table names and no offline Amazon report dependency
        call_args = mock_db_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "FROM meow_sku_map" in sql_text
        assert "amz_all_listing_report" not in sql_text

    def test_get_variation_data(self, repo, mock_db_session):
        # Mock result: list of (meow, vendor, list)
        mock_db_session.execute.return_value.fetchall.return_value = [
            ('M1', 'V1', ['V2']),
            ('M2', 'V2', ['V1'])
        ]
        
        data = repo.get_variation_data(['M1', 'M2'])
        
        assert len(data) == 2
        assert data[0] == ('M1', 'V1', ['V2'])
        
        # Verify parameters passed
        args, kwargs = mock_db_session.execute.call_args
        # execute(query, params) -> params is args[1]
        params = args[1]
        assert params['meow_sku_list'] == ['M1', 'M2']
    
    def test_get_sku_to_category_mapping(self, repo, mock_db_session):
        mock_db_session.execute.return_value.fetchall.return_value = [
            ('M1', 'CABINET')
        ]
        
        mapping = repo.get_sku_to_category_mapping(['M1'])
        
        assert mapping == [('M1', 'CABINET')]
