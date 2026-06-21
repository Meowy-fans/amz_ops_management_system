import json
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.product_detail_generation_service import ProductDetailGenerationService
from src.services.progress_reporter import NullProgressReporter


def _review_pass_response():
    return MagicMock(
        provider='fake',
        content=json.dumps({
            'verdict': 'pass',
            'accuracy_score': 0.95,
            'compliance_score': 1.0,
            'amazon_readiness_score': 0.9,
            'issues': [],
            'revision_instructions': '',
            'manual_review_fields': [],
        }),
    )


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
            'name': '30 inch bathroom vanity',
            'description': '<p>Wood cabinet</p>',
            'imageUrls': ['https://cdn.example.com/a.jpg'],
            'category': 'Bathroom Vanities',
        }
        thread_repo.get_product_type_for_sku.return_value = 'CABINET'
        thread_db = MagicMock()
        MockSessionLocal.return_value.__enter__.return_value = thread_db
        llm_response = MagicMock(
            provider='fake',
            content=json.dumps({
                'title': 'Modern Bathroom Cabinet',
                'bullet_1': 'Solid Wood: Durable cabinet for daily bathroom storage',
                'bullet_2': 'Compact Fit: Designed for 30 inch vanity spaces',
                'bullet_3': 'Easy Use: Smooth drawer access for essentials',
                'bullet_4': 'Bathroom Ready: Works in remodel or replacement projects',
                'bullet_5': 'Quality Build: Uses factual material details from supplier data',
                'description': '<b>Bathroom Storage</b><br/>A cabinet for organized daily use.',
                'search_terms': 'bathroom cabinet,vanity storage',
                'generic_keyword': 'bathroom vanity cabinet',
            }),
        )
        mock_get_llm_service.return_value.generate.side_effect = [
            llm_response,
            _review_pass_response(),
        ]

        service = ProductDetailGenerationService(mock_db)

        result = service.process_single_sku('SKU1')

        assert result[:9] == (
            'SKU1',
            'Modern Bathroom Cabinet',
            'Solid Wood: Durable cabinet for daily bathroom storage',
            'Compact Fit: Designed for 30 inch vanity spaces',
            'Easy Use: Smooth drawer access for essentials',
            'Bathroom Ready: Works in remodel or replacement projects',
            'Quality Build: Uses factual material details from supplier data',
            '<b>Bathroom Storage</b><br/>A cabinet for organized daily use.',
            'product_content_generator_v2',
        )
        raw_json = json.loads(result[9])
        assert raw_json["generator_version"] == "v2"
        assert raw_json["product_type"] == "CABINET"
        assert raw_json["search_terms"] == "bathroom cabinet,vanity storage"
        assert raw_json["generic_keyword"] == "bathroom vanity cabinet"
        assert raw_json["validation_warnings"] == []
        assert raw_json["review_status"] == "pass"
        assert raw_json["review_attempts"] == 1
        thread_repo.get_product_raw_data.assert_called_once_with('SKU1')
        thread_repo.get_product_type_for_sku.assert_called_once_with('SKU1')
        assert mock_get_llm_service.return_value.generate.call_count == 2

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
        thread_repo.get_product_type_for_sku.return_value = None
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()

        service = ProductDetailGenerationService(mock_db)
        service.content_generator._get_prompt = MagicMock(return_value=None)

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
        thread_repo.get_product_raw_data.return_value = {
            'sku': 'SKU1',
            'name': 'Bathroom cabinet',
        }
        thread_repo.get_product_type_for_sku.return_value = 'CABINET'
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()
        mock_get_llm_service.return_value.generate.side_effect = [
            RuntimeError('temporary'),
            MagicMock(
                provider='fake',
                content=json.dumps({
                    'title': 'Retry Cabinet',
                    'bullet_1': 'Storage Design: Keeps essentials organized',
                    'description': 'Generated after retry',
                }),
            ),
            _review_pass_response(),
        ]

        service = ProductDetailGenerationService(mock_db, max_retries=2)

        result = service.process_single_sku('SKU1')

        assert result[1] == 'Retry Cabinet'
        assert result[7] == 'Generated after retry'
        mock_sleep.assert_called_once_with(1)
        assert mock_get_llm_service.return_value.generate.call_count == 3

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
        thread_repo.get_product_raw_data.return_value = {
            'sku': 'SKU1',
            'name': 'Bathroom cabinet',
        }
        thread_repo.get_product_type_for_sku.return_value = 'CABINET'
        MockSessionLocal.return_value.__enter__.return_value = MagicMock()
        mock_get_llm_service.return_value.generate.side_effect = RuntimeError('down')

        service = ProductDetailGenerationService(mock_db, max_retries=2)

        assert service.process_single_sku('SKU1') is None
        mock_sleep.assert_called_once_with(1)

    def test_build_detail_tuple_preserves_v2_output_and_warnings(
        self,
        MockRepository,
        mock_get_llm_service,
    ):
        service = ProductDetailGenerationService(MagicMock(spec=Session))
        content = MagicMock(
            title='Cabinet',
            bullet_1='Point 1',
            bullet_2='Point 2',
            bullet_3='',
            bullet_4='',
            bullet_5='',
            description='Description',
            search_terms='cabinet,storage',
            generic_keyword='cabinet',
            enriched_attributes={'room_type': 'Bathroom'},
            validation_warnings=['warning'],
            validation_errors=[],
            compliance_hits=[],
            compliance_fixes=[],
            compliance_blocked=False,
            auto_sanitized=False,
            compliance_retried=False,
            review_status='pass',
            review_attempts=1,
            review_result={'verdict': 'pass'},
        )

        result = service._build_detail_tuple('GIGA-1', 'CABINET', content)

        assert result[:8] == (
            'GIGA-1',
            'Cabinet',
            'Point 1',
            'Point 2',
            '',
            '',
            '',
            'Description',
        )
        raw_json = json.loads(result[9])
        assert raw_json['enriched_attributes'] == {'room_type': 'Bathroom'}
        assert raw_json['validation_warnings'] == ['warning']
        assert raw_json['review_status'] == 'pass'
        assert raw_json['review_attempts'] == 1
        assert raw_json['review_result'] == {'verdict': 'pass'}

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
