from unittest.mock import MagicMock, patch

from infrastructure.llm.types import LLMResponse
from src.services.variation_theme_service import VariationThemeService


class TestVariationThemeService:
    def _make_service(self, prompt_side_effect=None, llm_side_effect=None):
        with patch('src.services.variation_theme_service.get_llm_service') as mock_get_llm, \
             patch('src.services.variation_theme_service.PromptManager') as MockPromptManager:
            mock_llm = mock_get_llm.return_value
            mock_prompt_manager = MockPromptManager.return_value
            if prompt_side_effect is not None:
                mock_prompt_manager.get_prompt.side_effect = prompt_side_effect
            else:
                mock_prompt_manager.get_prompt.return_value = "system prompt"
            if llm_side_effect is not None:
                mock_llm.generate.side_effect = llm_side_effect

            service = VariationThemeService()

        return service, mock_llm, mock_prompt_manager

    def test_determine_variation_theme_returns_first_round_when_unique(self):
        service, mock_llm, _ = self._make_service(
            llm_side_effect=[
                LLMResponse(content={
                    'variation_theme': 'Color/Size',
                    'child_attributes': {
                        'SKU1': {'color_name': 'White', 'size_name': '19.6'},
                        'SKU2': {'color_name': 'Black', 'size_name': '20.2'}
                    }
                })
            ]
        )
        family_data = [
            {
                'meow_sku': 'SKU1',
                'product_name': 'White mirror',
                'product_description': '<p>White</p>',
                'raw_data': {'assembledHeight': 19.6}
            },
            {
                'meow_sku': 'SKU2',
                'product_name': 'Black mirror',
                'product_description': '<p>Black</p>',
                'raw_data': {'assembledHeight': 20.2}
            }
        ]

        result = service.determine_variation_theme(
            family_data,
            valid_themes=['Color', 'Color/Size'],
            priority_themes=['Color/Size', 'Invalid']
        )

        assert result['variation_theme'] == 'Color/Size'
        assert result['child_attributes']['SKU1']['size_name'] == '20'
        assert result['child_attributes']['SKU2']['size_name'] == '20'
        mock_llm.generate.assert_called_once()
        request = mock_llm.generate.call_args[0][0]
        assert request.task_type == 'product_attribute_enrichment'
        assert request.json_mode is True
        assert 'Color/Size' in request.user_prompt
        assert '<p>' not in request.user_prompt

    def test_determine_variation_theme_uses_second_round_when_duplicate(self):
        service, mock_llm, _ = self._make_service(
            llm_side_effect=[
                LLMResponse(content={
                    'variation_theme': 'Color',
                    'child_attributes': {
                        'SKU1': {'color_name': 'White'},
                        'SKU2': {'color_name': 'White'}
                    }
                }),
                LLMResponse(content={
                    'variation_theme': 'Color/Size',
                    'child_attributes': {
                        'SKU1': {'color_name': 'White', 'size_name': '36'},
                        'SKU2': {'color_name': 'White', 'size_name': '48'}
                    }
                })
            ]
        )

        result = service.determine_variation_theme(
            [{'meow_sku': 'SKU1'}, {'meow_sku': 'SKU2'}],
            valid_themes=['Color', 'Color/Size'],
            priority_themes=['Color/Size']
        )

        assert result['variation_theme'] == 'Color/Size'
        assert result['child_attributes']['SKU2']['size_name'] == '48'
        assert mock_llm.generate.call_count == 2

    def test_first_round_returns_default_when_prompt_missing(self):
        service, mock_llm, _ = self._make_service(prompt_side_effect=[None])

        result = service._first_round_determination(
            [{'meow_sku': 'SKU1'}],
            valid_themes=['Color'],
            priority_themes=[]
        )

        assert result == {'variation_theme': 'Color', 'child_attributes': {}}
        mock_llm.generate.assert_not_called()

    def test_second_round_returns_failed_theme_on_llm_error(self):
        service, mock_llm, _ = self._make_service(
            llm_side_effect=[RuntimeError("llm failed")]
        )

        result = service._second_round_correction(
            [{'meow_sku': 'SKU1'}],
            valid_themes=['Color'],
            priority_themes=[],
            failed_theme='Size'
        )

        assert result == {'variation_theme': 'Size', 'child_attributes': {}}
        mock_llm.generate.assert_called_once()

    def test_check_attribute_uniqueness_detects_duplicates(self):
        assert VariationThemeService._check_attribute_uniqueness({
            'SKU1': {'color_name': 'White'},
            'SKU2': {'color_name': 'White'}
        }) is False
        assert VariationThemeService._check_attribute_uniqueness({
            'SKU1': {'color_name': 'White'},
            'SKU2': {'color_name': 'Black'}
        }) is True

    def test_strip_html_and_format_attributes(self):
        assert VariationThemeService._strip_html("<p>Hello<br> World</p>") == "Hello World"
        assert VariationThemeService._format_variation_attributes({
            'SKU1': {'size_name': '19.6', 'color_name': 'White'},
            'SKU2': {'size_name': 'bad'}
        }) == {
            'SKU1': {'size_name': '20', 'color_name': 'White'},
            'SKU2': {'size_name': 'bad'}
        }
