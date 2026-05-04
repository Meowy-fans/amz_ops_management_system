from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from src.services.amz_full_list_importer_service import AmzFullListImporterService
from src.services.progress_reporter import NullProgressReporter


class TestAmzFullListImporterService:
    def test_import_report_with_null_reporter_does_not_print(self, capsys):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_full_list_importer_service.AmzFullListReportRepository'
        ) as MockRepository, patch(
            'src.services.amz_full_list_importer_service.validate_file_path',
            return_value='report.txt'
        ):
            mock_repository = MockRepository.return_value
            mock_repository.get_statistics.return_value = {
                'total': 2,
                'active': 1,
                'unique_asins': 2
            }
            service = AmzFullListImporterService(mock_db, reporter=NullProgressReporter())
            service._read_file = MagicMock(return_value=pd.DataFrame([
                {
                    'listing-id': 'L1',
                    'seller-sku': 'SKU1',
                    'asin1': 'ASIN1',
                    'item-name': 'Item',
                    'price': '10.5',
                    'quantity': '3',
                    'open-date': '2026-01-01',
                    'status': 'Active'
                }
            ]))

            service.import_report_from_file('report.txt')

        mock_repository.upsert_from_dataframe.assert_called_once()
        mock_db.commit.assert_called_once()
        assert capsys.readouterr().out == ""

    def test_import_report_rolls_back_on_error(self):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_full_list_importer_service.AmzFullListReportRepository'
        ), patch(
            'src.services.amz_full_list_importer_service.validate_file_path',
            side_effect=ValueError("bad path")
        ):
            service = AmzFullListImporterService(mock_db, reporter=NullProgressReporter())

            with pytest.raises(ValueError):
                service.import_report_from_file('bad.txt')

        mock_db.rollback.assert_called_once()
