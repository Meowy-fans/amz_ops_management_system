from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.product_detail_generation_service import ProductDetailGenerationService
from src.services.progress_reporter import NullProgressReporter


@patch('src.services.product_detail_generation_service.get_llm_service')
@patch('src.services.product_detail_generation_service.LLMProductDetailRepository')
class TestProductDetailGenerationService:
    def test_process_all_skus_with_null_reporter_does_not_print_when_empty(
        self,
        MockRepository,
        mock_get_llm_service,
        capsys
    ):
        mock_db = MagicMock(spec=Session)
        mock_repository = MockRepository.return_value
        mock_repository.get_unprocessed_skus.return_value = []

        service = ProductDetailGenerationService(mock_db, reporter=NullProgressReporter())

        result = service.process_all_skus()

        assert result is None
        mock_repository.get_unprocessed_skus.assert_called_once()
        assert capsys.readouterr().out == ""

    @patch('src.services.product_detail_generation_service.time.sleep')
    def test_process_all_skus_with_null_reporter_does_not_print_for_batches(
        self,
        mock_sleep,
        MockRepository,
        mock_get_llm_service,
        capsys
    ):
        mock_db = MagicMock(spec=Session)
        mock_repository = MockRepository.return_value
        mock_repository.get_unprocessed_skus.return_value = ['SKU1', 'SKU2', 'SKU3']

        service = ProductDetailGenerationService(
            mock_db,
            batch_size=2,
            reporter=NullProgressReporter()
        )

        def process_batch(batch):
            service.processed_count += len(batch)
            return len(batch)

        service.process_batch = MagicMock(side_effect=process_batch)

        service.process_all_skus()

        assert service.process_batch.call_count == 2
        assert service.processed_count == 3
        assert capsys.readouterr().out == ""
