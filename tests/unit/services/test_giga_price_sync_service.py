from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.giga_price_sync_service import GigaPriceSyncService
from src.services.progress_reporter import NullProgressReporter


@patch('src.services.giga_price_sync_service.time.sleep')
class TestGigaPriceSyncService:
    def test_sync_all_prices_with_null_reporter_does_not_print(
        self,
        mock_sleep,
        capsys
    ):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.giga_price_sync_service.GigaProductPriceRepository') as MockRepo, \
             patch('src.services.giga_price_sync_service.GigaAPIClient'):
            mock_repo = MockRepo.return_value
            mock_repo.get_all_skus.return_value = []
            service = GigaPriceSyncService(mock_db, reporter=NullProgressReporter())

            result = service.sync_all_prices()

        assert result == {'total': 0, 'success': 0, 'failed': 0}
        assert capsys.readouterr().out == ""

    def test_fetch_batch_prices_with_null_reporter_does_not_print(
        self,
        mock_sleep,
        capsys
    ):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.giga_price_sync_service.GigaProductPriceRepository'), \
             patch('src.services.giga_price_sync_service.GigaAPIClient') as MockClient:
            mock_client = MockClient.return_value
            mock_client.execute.return_value = {
                'body': {
                    'success': True,
                    'data': [{'sku': 'SKU1', 'price': 10.0}]
                }
            }
            service = GigaPriceSyncService(mock_db, reporter=NullProgressReporter())

            prices = service.fetch_batch_prices(['SKU1'])

        assert prices == [{'sku': 'SKU1', 'price': 10.0}]
        assert capsys.readouterr().out == ""
