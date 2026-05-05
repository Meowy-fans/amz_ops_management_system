import json
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.product_detail_generation_service import ProductDetailGenerationService
from src.services.progress_reporter import NullProgressReporter


@patch('src.services.product_detail_generation_service.get_llm_service')
@patch('src.services.product_detail_generation_service.LLMProductDetailRepository')
class TestProductDetailGenerationService:
    @patch('src.services.product_detail_generation_service.SessionLocal')
    def test_process_single_sku_generates_and_fills_missing_fields(
        self,
        MockSessionLocal,
        MockRepository,
        mock_get_llm_service,
    ):
        mock_db = MagicMock(spec=Session)
        main_repo = MagicMock()
        thread_repo = MagicMock()
        MockRepository.side_effect = [main_repo, thread_repo]
        thread_repo.get_product_raw_data.return_value = {
            'sku': 'SKU1',
            'description': '<p>Wood cabinet</p>',
            'imageUrls': ['https://cdn.example.com/a.jpg'],
        }
        thread_db = MagicMock()
        MockSessionLocal.return_value.__enter__.return_value = thread_db
        llm_response = MagicMock(
            provider='fake',
            content={
                '产品名称': 'Modern Cabinet',
                '产品卖点 1': 'Solid wood',
                '产品描述': 'A cabinet',
            },
        )
        mock_get_llm_service.return_value.generate.return_value = llm_response

        service = ProductDetailGenerationService(mock_db)
        service.prompt_manager.get_prompt = MagicMock(return_value='system prompt')

        result = service.process_single_sku('SKU1')

        assert result[:9] == (
            'SKU1',
            'Modern Cabinet',
            'Solid wood',
            '',
            '',
            '',
            '',
            'A cabinet',
            'llm_service_fake',
        )
        assert json.loads(result[9]) == {
            '产品名称': 'Modern Cabinet',
            '产品卖点 1': 'Solid wood',
            '产品描述': 'A cabinet',
            '产品卖点 2': '',
            '产品卖点 3': '',
            '产品卖点 4': '',
            '产品卖点 5': '',
        }
        thread_repo.get_product_raw_data.assert_called_once_with('SKU1')
        mock_get_llm_service.return_value.generate.assert_called_once()

    @patch('src.services.product_detail_generation_service.SessionLocal')
    def test_process_single_sku_returns_none_when_raw_data_missing(
        self,
        MockSessionLocal,
        MockRepository,
        mock_get_llm_service,
    ):
        mock_db = MagicMock(spec=Session)
        thread_repo = MagicMock()
        MockRepository.side_effect = [MagicMock(), thread_repo]
        thread_repo.get_product_raw_data.return_value = None
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()

        service = ProductDetailGenerationService(mock_db)

        assert service.process_single_sku('SKU1') is None
        mock_get_llm_service.return_value.generate.assert_not_called()

    @patch('src.services.product_detail_generation_service.SessionLocal')
    def test_process_single_sku_returns_none_when_prompt_missing(
        self,
        MockSessionLocal,
        MockRepository,
        mock_get_llm_service,
    ):
        mock_db = MagicMock(spec=Session)
        thread_repo = MagicMock()
        MockRepository.side_effect = [MagicMock(), thread_repo]
        thread_repo.get_product_raw_data.return_value = {'sku': 'SKU1'}
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()

        service = ProductDetailGenerationService(mock_db)
        service.prompt_manager.get_prompt = MagicMock(return_value=None)

        assert service.process_single_sku('SKU1') is None
        mock_get_llm_service.return_value.generate.assert_not_called()

    @patch('src.services.product_detail_generation_service.time.sleep')
    @patch('src.services.product_detail_generation_service.SessionLocal')
    def test_process_single_sku_retries_llm_failures_then_succeeds(
        self,
        MockSessionLocal,
        mock_sleep,
        MockRepository,
        mock_get_llm_service,
    ):
        mock_db = MagicMock(spec=Session)
        thread_repo = MagicMock()
        MockRepository.side_effect = [MagicMock(), thread_repo]
        thread_repo.get_product_raw_data.return_value = {'sku': 'SKU1'}
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()
        mock_get_llm_service.return_value.generate.side_effect = [
            RuntimeError('temporary'),
            MagicMock(
                provider='fake',
                content={
                    '产品名称': 'Retry Cabinet',
                    '产品描述': 'Generated after retry',
                },
            ),
        ]

        service = ProductDetailGenerationService(mock_db, max_retries=2)
        service.prompt_manager.get_prompt = MagicMock(return_value='system prompt')

        result = service.process_single_sku('SKU1')

        assert result[1] == 'Retry Cabinet'
        assert result[7] == 'Generated after retry'
        mock_sleep.assert_called_once_with(1)
        assert mock_get_llm_service.return_value.generate.call_count == 2

    @patch('src.services.product_detail_generation_service.time.sleep')
    @patch('src.services.product_detail_generation_service.SessionLocal')
    def test_process_single_sku_returns_none_after_final_llm_failure(
        self,
        MockSessionLocal,
        mock_sleep,
        MockRepository,
        mock_get_llm_service,
    ):
        mock_db = MagicMock(spec=Session)
        thread_repo = MagicMock()
        MockRepository.side_effect = [MagicMock(), thread_repo]
        thread_repo.get_product_raw_data.return_value = {'sku': 'SKU1'}
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()
        mock_get_llm_service.return_value.generate.side_effect = RuntimeError('down')

        service = ProductDetailGenerationService(mock_db, max_retries=2)
        service.prompt_manager.get_prompt = MagicMock(return_value='system prompt')

        assert service.process_single_sku('SKU1') is None
        mock_sleep.assert_called_once_with(1)

    def test_validate_and_fill_result_adds_required_keys(
        self,
        MockRepository,
        mock_get_llm_service,
    ):
        service = ProductDetailGenerationService(MagicMock(spec=Session))
        result = {'产品名称': 'Cabinet'}

        service._validate_and_fill_result(result)

        assert result == {
            '产品名称': 'Cabinet',
            '产品描述': '',
            '产品卖点 1': '',
            '产品卖点 2': '',
            '产品卖点 3': '',
            '产品卖点 4': '',
            '产品卖点 5': '',
        }

    def test_process_batch_saves_successful_results_and_updates_statistics(
        self,
        MockRepository,
        mock_get_llm_service,
    ):
        mock_db = MagicMock(spec=Session)
        mock_repository = MockRepository.return_value
        mock_repository.batch_save_details.return_value = 1
        service = ProductDetailGenerationService(mock_db, thread_count=1)

        def process_single_sku(sku):
            if sku == 'SKU1':
                return ('SKU1', 'name')
            raise RuntimeError('thread failed')

        service.process_single_sku = MagicMock(side_effect=process_single_sku)

        saved_count = service.process_batch(['SKU1', 'SKU2'])

        assert saved_count == 1
        mock_repository.batch_save_details.assert_called_once_with([('SKU1', 'name')])
        assert service.processed_count == 1
        assert service.failed_count == 1

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
