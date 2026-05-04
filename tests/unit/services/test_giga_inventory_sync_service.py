import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy.orm import Session
from src.services.giga_inventory_sync_service import GigaInventorySyncService
from infrastructure.giga.api_client import GigaAPIException
from src.services.progress_reporter import NullProgressReporter

@patch('src.services.giga_inventory_sync_service.time.sleep')
class TestGigaInventorySyncService:
    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_api_client(self):
        with patch('src.services.giga_inventory_sync_service.GigaAPIClient') as MockClient:
            yield MockClient.return_value

    @pytest.fixture
    def mock_repo(self):
        with patch('src.services.giga_inventory_sync_service.GigaProductInventoryRepository') as MockRepo:
            yield MockRepo.return_value

    @pytest.fixture
    def service(self, mock_db, mock_api_client, mock_repo):
        service = GigaInventorySyncService(mock_db)
        service.api_client = mock_api_client
        service.repository = mock_repo
        return service

    def test_fetch_batch_inventory_success(self, mock_sleep, service, mock_api_client):
        mock_api_client.execute.return_value = {
            'body': {'data': [{'sku': 'SKU1', 'qty': 10}]}
        }
        
        result = service.fetch_batch_inventory(['SKU1'])
        
        assert result['data'][0]['sku'] == 'SKU1'
        mock_api_client.execute.assert_called_once()

    def test_fetch_batch_inventory_retry_success(self, mock_sleep, service, mock_api_client):
        # Fail twice, then succeed
        mock_api_client.execute.side_effect = [
            Exception("Network Error"),
            Exception("Network Error"),
            {'body': {'data': []}}
        ]
        
        service.fetch_batch_inventory(['SKU1'])
        
        assert mock_api_client.execute.call_count == 3

    def test_fetch_batch_inventory_failure(self, mock_sleep, service, mock_api_client):
        # Fail 3 times (max_retries=3 by default)
        mock_api_client.execute.side_effect = Exception("Persistent Error")
        
        with pytest.raises(Exception):
            service.fetch_batch_inventory(['SKU1'])
            
        assert mock_api_client.execute.call_count == 3

    @patch('src.services.giga_inventory_sync_service.SessionLocal')
    @patch('src.services.giga_inventory_sync_service.GigaProductInventoryRepository')
    def test_process_batch_success(self, MockRepoClass, MockSessionLocal, mock_sleep, service, mock_api_client):
        # Mock thread-local DB and Repo
        mock_thread_db = MagicMock()
        MockSessionLocal.return_value.__enter__.return_value = mock_thread_db
        mock_thread_repo = MockRepoClass.return_value
        
        # Mock API response
        mock_api_client.execute.return_value = {
            'body': {'data': [{'sku': 'SKU1', 'quantity': 10}]}
        }
        
        # Mock parsing and upserting
        mock_thread_repo.parse_inventory_item.return_value = {'sku': 'SKU1', 'quantity': 10}
        mock_thread_repo.bulk_upsert_inventory.return_value = (1, 1) # processed, upserted
        
        processed, upserted = service.process_batch(1, ['SKU1'])
        
        assert processed == 1
        assert upserted == 1
        MockSessionLocal.assert_called_once() # Should open a new session

    def test_sync_all_inventory_success(self, mock_sleep, service, mock_repo):
        # Mock repository returning SKUs
        mock_repo.get_all_skus.return_value = ['SKU1', 'SKU2']
        service.batch_size = 1
        service.process_batch = MagicMock(side_effect=[(1, 1), (1, 1)])

        stats = service.sync_all_inventory()

        assert stats['total_skus'] == 2
        assert stats['batches'] == 2
        assert stats['processed'] == 2
        assert stats['upserted'] == 2
        assert stats['success_batches'] == 2
        assert service.process_batch.call_count == 2
        
    def test_sync_all_inventory_no_skus(self, mock_sleep, service, mock_repo):
        mock_repo.get_all_skus.return_value = []
        
        stats = service.sync_all_inventory()
        
        assert stats['total_skus'] == 0
        assert stats['processed'] == 0

    def test_sync_all_inventory_with_null_reporter_does_not_print(
        self,
        mock_sleep,
        mock_db,
        mock_api_client,
        mock_repo,
        capsys
    ):
        service = GigaInventorySyncService(mock_db, reporter=NullProgressReporter())
        service.api_client = mock_api_client
        service.repository = mock_repo
        mock_repo.get_all_skus.return_value = []

        stats = service.sync_all_inventory()

        assert stats['total_skus'] == 0
        assert capsys.readouterr().out == ""
