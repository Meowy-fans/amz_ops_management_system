import pytest
from unittest.mock import MagicMock, call, patch
from sqlalchemy.orm import Session
from src.services.giga_sync_service import GigaSyncService
from infrastructure.giga.api_client import GigaAPIException
from src.services.progress_reporter import NullProgressReporter

@patch('src.services.giga_sync_service.time.sleep')
class TestGigaSyncService:
    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_api_client(self):
        with patch('src.services.giga_sync_service.GigaAPIClient') as MockClient:
            yield MockClient.return_value

    @pytest.fixture
    def mock_repo(self):
        with patch('src.services.giga_sync_service.GigaProductSyncRepository') as MockRepo:
            yield MockRepo.return_value

    @pytest.fixture
    def service(self, mock_db, mock_api_client, mock_repo):
        service = GigaSyncService(mock_db)
        # Ensure the service uses the mocked instances
        service.api_client = mock_api_client
        service.repository = mock_repo
        return service

    def test_get_full_sku_list_success(self, mock_sleep, service, mock_api_client):
        # Mock API responses for 2 pages
        mock_api_client.execute.side_effect = [
            # Page 1
            {
                'body': {
                    'pageMeta': {'total': 3, 'next': True},
                    'data': [{'sku': 'SKU1'}, {'sku': 'SKU2'}]
                },
                'headers': {'X-RateLimit-Remaining': '10'}
            },
            # Page 2
            {
                'body': {
                    'pageMeta': {'total': 3, 'next': False},
                    'data': [{'sku': 'SKU3'}]
                },
                'headers': {'X-RateLimit-Remaining': '10'}
            }
        ]

        skus = service.get_full_sku_list(limit_per_page=2)

        assert len(skus) == 3
        assert skus == ['SKU1', 'SKU2', 'SKU3']
        assert mock_api_client.execute.call_count == 2

    def test_get_full_sku_list_api_error(self, mock_sleep, service, mock_api_client):
        # Mock API error on first call
        mock_api_client.execute.side_effect = GigaAPIException("API Error")

        skus = service.get_full_sku_list()

        assert len(skus) == 0
        assert mock_api_client.execute.call_count == 1

    def test_sync_product_details_success(self, mock_sleep, service, mock_api_client, mock_repo, mock_db):
        sku_list = ['SKU1', 'SKU2', 'SKU3']
        
        # Mock API response
        mock_api_client.execute.return_value = {
            'body': {
                'data': [
                    {'sku': 'SKU1', 'name': 'Product 1'},
                    {'sku': 'SKU2', 'name': 'Product 2'},
                    {'sku': 'SKU3', 'name': 'Product 3'}
                ]
            }
        }
        
        # Mock repository return value
        mock_repo.batch_upsert_products.return_value = 3

        result = service.sync_product_details(sku_list, batch_size=10)

        assert result['total'] == 3
        assert result['success'] == 3
        assert result['failed'] == 0
        
        mock_api_client.execute.assert_called_once()
        mock_repo.batch_upsert_products.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_sync_product_details_partial_failure(self, mock_sleep, service, mock_api_client, mock_repo, mock_db):
        sku_list = ['SKU1', 'SKU2']
        
        # Mock API failure for the batch
        mock_api_client.execute.side_effect = GigaAPIException("Batch Failed")

        result = service.sync_product_details(sku_list, batch_size=10)

        assert result['total'] == 2
        assert result['success'] == 0
        assert result['failed'] == 2
        
        mock_db.rollback.assert_called_once()
        mock_repo.batch_upsert_products.assert_not_called()

    def test_sync_product_details_batching(self, mock_sleep, service, mock_api_client, mock_repo, mock_db):
        sku_list = ['SKU1', 'SKU2', 'SKU3']
        
        # Mock API responses for 2 batches (batch_size=2)
        mock_api_client.execute.side_effect = [
            {'body': {'data': [{'sku': 'SKU1'}, {'sku': 'SKU2'}]}},
            {'body': {'data': [{'sku': 'SKU3'}]}}
        ]
        
        mock_repo.batch_upsert_products.side_effect = [2, 1]

        result = service.sync_product_details(sku_list, batch_size=2)

        assert result['total'] == 3
        assert result['success'] == 3
        mock_api_client.execute.call_count == 2
        mock_db.commit.call_count == 2

    def test_sync_full_products_with_null_reporter_does_not_print(
        self,
        mock_sleep,
        mock_db,
        mock_api_client,
        mock_repo,
        capsys
    ):
        service = GigaSyncService(mock_db, reporter=NullProgressReporter())
        service.api_client = mock_api_client
        service.repository = mock_repo
        service.get_full_sku_list = MagicMock(return_value=[])

        result = service.sync_full_products()

        assert result == {'total': 0, 'success': 0, 'failed': 0}
        assert capsys.readouterr().out == ""
