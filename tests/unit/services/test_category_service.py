from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.category_service import CategoryService
from src.services.progress_reporter import NullProgressReporter


class TestCategoryService:
    def test_categorize_skus_with_null_reporter_does_not_print(self, capsys):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.category_service.CategoryRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.get_sku_to_category_mapping.return_value = [
                ('SKU1', 'HOME'),
                ('SKU2', None)
            ]
            service = CategoryService(mock_db, reporter=NullProgressReporter())

            categorized, uncategorized = service.categorize_skus(['SKU1', 'SKU2', 'SKU3'])

        assert categorized == {'HOME': ['SKU1']}
        assert uncategorized == ['SKU2', 'SKU3']
        assert capsys.readouterr().out == ""

    def test_categorize_skus_empty_input_does_not_query(self):
        mock_db = MagicMock(spec=Session)

        with patch('src.services.category_service.CategoryRepository') as MockRepository:
            mock_repo = MockRepository.return_value
            service = CategoryService(mock_db, reporter=NullProgressReporter())

            categorized, uncategorized = service.categorize_skus([])

        assert categorized == {}
        assert uncategorized == []
        mock_repo.get_sku_to_category_mapping.assert_not_called()
