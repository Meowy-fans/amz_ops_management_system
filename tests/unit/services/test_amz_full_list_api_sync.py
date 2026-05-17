from unittest.mock import MagicMock, patch

import pandas as pd
from sqlalchemy.orm import Session

from src.services.amz_full_list_importer_service import AmzFullListImporterService
from src.services.progress_reporter import NullProgressReporter


class FakeReportsClient:
    def __init__(self):
        self.calls = []

    def create_merchant_listings_report(self):
        self.calls.append("create")
        return "R1"

    def wait_for_report(self, report_id):
        self.calls.append(("wait", report_id))
        return "D1"

    def get_report_document(self, document_id):
        self.calls.append(("document", document_id))
        return {"url": "https://doc.example/report.txt"}

    def download_report_document(self, document):
        self.calls.append(("download", document["url"]))
        return (
            "listing-id\tseller-sku\tasin1\titem-name\tprice\tquantity\topen-date\tstatus\n"
            "L1\tSKU1\tASIN1\tItem 1\t10.5\t3\t2026-01-01\tActive\n"
        )


def test_sync_report_from_api_reuses_cleaning_and_repository_upsert(capsys):
    mock_db = MagicMock(spec=Session)
    fake_client = FakeReportsClient()

    with patch(
        "src.services.amz_full_list_importer_service.AmzFullListReportRepository"
    ) as MockRepository:
        repository = MockRepository.return_value
        repository.get_statistics.return_value = {
            "total": 1,
            "active": 1,
            "unique_asins": 1,
        }
        service = AmzFullListImporterService(
            mock_db,
            reporter=NullProgressReporter(),
            reports_client=fake_client,
        )

        result = service.sync_report_from_api()

    repository.upsert_from_dataframe.assert_called_once()
    upsert_df = repository.upsert_from_dataframe.call_args.args[0]
    assert isinstance(upsert_df, pd.DataFrame)
    assert list(upsert_df["listing-id"]) == ["L1"]
    assert result == {
        "report_id": "R1",
        "document_id": "D1",
        "statistics": {"total": 1, "active": 1, "unique_asins": 1},
    }
    assert fake_client.calls == [
        "create",
        ("wait", "R1"),
        ("document", "D1"),
        ("download", "https://doc.example/report.txt"),
    ]
    mock_db.commit.assert_called_once()
    assert capsys.readouterr().out == ""


def test_sync_report_from_api_rolls_back_on_error():
    mock_db = MagicMock(spec=Session)
    fake_client = FakeReportsClient()
    fake_client.download_report_document = MagicMock(side_effect=RuntimeError("download failed"))
    service = AmzFullListImporterService(
        mock_db,
        reporter=NullProgressReporter(),
        reports_client=fake_client,
    )

    try:
        service.sync_report_from_api()
    except RuntimeError as exc:
        assert str(exc) == "download failed"

    mock_db.rollback.assert_called_once()
