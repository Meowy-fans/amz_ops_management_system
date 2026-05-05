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

    def test_read_file_supports_csv_and_tsv(self, tmp_path):
        service = AmzFullListImporterService(MagicMock(spec=Session), reporter=NullProgressReporter())
        csv_path = tmp_path / "report.csv"
        tsv_path = tmp_path / "report.txt"
        csv_path.write_text("listing-id,asin1\nL1,A1\n", encoding="utf-8")
        tsv_path.write_text("listing-id\tasin1\nL2\tA2\n", encoding="utf-8")

        csv_df = service._read_file(str(csv_path))
        tsv_df = service._read_file(str(tsv_path))

        assert csv_df.iloc[0]["listing-id"] == "L1"
        assert tsv_df.iloc[0]["asin1"] == "A2"

    def test_read_file_raises_when_all_encodings_fail(self, tmp_path):
        service = AmzFullListImporterService(MagicMock(spec=Session), reporter=NullProgressReporter())
        bad_path = tmp_path / "bad.csv"
        bad_path.write_bytes(b"\xff\xfe\x00\x80")

        with pytest.raises(ValueError, match="无法解析文件"):
            service._read_file(str(bad_path))

    def test_clean_data_coerces_types_drops_invalid_and_deduplicates(self):
        service = AmzFullListImporterService(MagicMock(spec=Session), reporter=NullProgressReporter())
        df = pd.DataFrame([
            {
                "listing-id": "L1",
                "seller-sku": "SKU1",
                "asin1": "ASIN1",
                "item-name": "Item 1",
                "price": "10.5",
                "quantity": "3",
                "open-date": "2026-01-01",
                "status": "Active",
                "ignored": "x",
            },
            {
                "listing-id": "L1",
                "seller-sku": "SKU1-DUP",
                "asin1": "ASIN1",
                "item-name": "Duplicate",
                "price": "bad",
                "quantity": "bad",
                "open-date": "bad",
                "status": "Inactive",
            },
            {
                "listing-id": " ",
                "seller-sku": "SKU2",
                "asin1": "ASIN2",
                "item-name": "Blank listing",
            },
            {
                "listing-id": "L3",
                "seller-sku": "SKU3",
                "asin1": None,
                "item-name": "Missing asin",
            },
        ])

        cleaned = service._clean_data(df)

        assert list(cleaned["listing-id"]) == ["L1"]
        assert list(cleaned.columns) == [
            "listing-id",
            "seller-sku",
            "asin1",
            "item-name",
            "price",
            "quantity",
            "open-date",
            "status",
        ]
        assert cleaned.iloc[0]["price"] == 10.5
        assert cleaned.iloc[0]["quantity"] == 3
