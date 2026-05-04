from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService
from src.services.progress_reporter import NullProgressReporter


class TestInventoryPriceUpdaterService:
    def test_generate_update_file_with_null_reporter_does_not_print_when_no_skus(
        self,
        capsys
    ):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_inventory_price_updater_service.ListingDataRepository'
        ) as MockRepository:
            mock_repository = MockRepository.return_value
            mock_repository.get_skus_for_update.return_value = []
            service = InventoryPriceUpdaterService(mock_db, reporter=NullProgressReporter())
            service._sync_latest_data = MagicMock()

            result = service.generate_update_file()

        assert result is None
        mock_repository.get_skus_for_update.assert_called_once()
        assert capsys.readouterr().out == ""

    @patch('src.services.amz_inventory_price_updater_service.GigaPriceSyncService')
    def test_sync_latest_data_handles_child_failure_with_null_reporter(
        self,
        MockPriceSyncService,
        capsys
    ):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_inventory_price_updater_service.ListingDataRepository'
        ):
            MockPriceSyncService.return_value.sync_all_prices.side_effect = RuntimeError("sync failed")
            service = InventoryPriceUpdaterService(mock_db, reporter=NullProgressReporter())

            service._sync_latest_data()

        MockPriceSyncService.return_value.sync_all_prices.assert_called_once()
        assert capsys.readouterr().out == ""

    @patch('src.services.amz_inventory_price_updater_service.PricingService')
    @patch('src.services.amz_inventory_price_updater_service.GigaInventorySyncService')
    @patch('src.services.amz_inventory_price_updater_service.GigaPriceSyncService')
    def test_sync_latest_data_passes_reporter_to_child_services(
        self,
        MockPriceSyncService,
        MockInventorySyncService,
        MockPricingService,
        capsys
    ):
        mock_db = MagicMock(spec=Session)
        reporter = NullProgressReporter()
        service = InventoryPriceUpdaterService(mock_db, reporter=reporter)

        service._sync_latest_data()

        MockPriceSyncService.assert_called_once_with(mock_db, reporter=reporter)
        MockInventorySyncService.assert_called_once_with(mock_db, reporter=reporter)
        MockPricingService.assert_called_once_with(mock_db, reporter=reporter)
        assert capsys.readouterr().out == ""
