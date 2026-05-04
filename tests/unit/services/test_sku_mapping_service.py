from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.sku_mapping_service import SkuMappingService


class TestSkuMappingService:
    def test_sync_mappings_returns_zero_when_no_source_skus(self):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.sku_mapping_service.SkuMappingRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.get_skus_from_llm_details.return_value = []
            service = SkuMappingService(mock_db)

            total, created = service.sync_mappings_from_llm_details()

        assert (total, created) == (0, 0)
        mock_repo.filter_unmapped_skus.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_sync_mappings_returns_total_when_all_mapped(self):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.sku_mapping_service.SkuMappingRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.get_skus_from_llm_details.return_value = ['SKU1', 'SKU2']
            mock_repo.filter_unmapped_skus.return_value = []
            service = SkuMappingService(mock_db)

            total, created = service.sync_mappings_from_llm_details()

        assert (total, created) == (2, 0)
        mock_repo.bulk_insert_mappings.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_sync_mappings_creates_new_mappings(self):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.sku_mapping_service.SkuMappingRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.get_skus_from_llm_details.return_value = ['SKU1', 'SKU2', 'SKU3']
            mock_repo.filter_unmapped_skus.return_value = ['SKU2', 'SKU3']
            service = SkuMappingService(mock_db)
            service._generate_meow_sku = MagicMock(side_effect=['meowA', 'meowB'])

            total, created = service.sync_mappings_from_llm_details()

        assert (total, created) == (3, 2)
        mock_repo.bulk_insert_mappings.assert_called_once_with([
            {'meow_sku': 'meowA', 'vendor_source': 'giga', 'vendor_sku': 'SKU2'},
            {'meow_sku': 'meowB', 'vendor_source': 'giga', 'vendor_sku': 'SKU3'}
        ])
        mock_db.commit.assert_called_once()

    def test_sync_mappings_rolls_back_on_insert_error(self):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.sku_mapping_service.SkuMappingRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.get_skus_from_llm_details.return_value = ['SKU1']
            mock_repo.filter_unmapped_skus.return_value = ['SKU1']
            mock_repo.bulk_insert_mappings.side_effect = RuntimeError("insert failed")
            service = SkuMappingService(mock_db)
            service._generate_meow_sku = MagicMock(return_value='meowA')

            total, created = service.sync_mappings_from_llm_details()

        assert (total, created) == (0, 0)
        mock_db.rollback.assert_called_once()

    def test_sync_mappings_fails_after_duplicate_generation_retries(self):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.sku_mapping_service.SkuMappingRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.get_skus_from_llm_details.return_value = ['SKU1', 'SKU2']
            mock_repo.filter_unmapped_skus.return_value = ['SKU1', 'SKU2']
            service = SkuMappingService(mock_db)
            service._generate_meow_sku = MagicMock(return_value='meowA')

            total, created = service.sync_mappings_from_llm_details()

        assert (total, created) == (0, 0)
        mock_repo.bulk_insert_mappings.assert_not_called()
        mock_db.rollback.assert_called_once()
