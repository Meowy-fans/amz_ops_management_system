from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.services.amz_asin_family_parent_listing_status_manager import ListingStatusManager
from src.services.progress_reporter import NullProgressReporter


class TestListingStatusManager:
    def test_update_statuses_with_null_reporter_does_not_print(self, capsys):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_asin_family_parent_listing_status_manager.AmzListingLogRepository'
        ) as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.bulk_update_status_to_listed.return_value = 2
            manager = ListingStatusManager(mock_db, reporter=NullProgressReporter())

            manager.update_statuses_to_listed()

        mock_repo.bulk_update_status_to_listed.assert_called_once()
        mock_db.commit.assert_called_once()
        assert capsys.readouterr().out == ""

    def test_update_statuses_rolls_back_on_exception(self, capsys):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_asin_family_parent_listing_status_manager.AmzListingLogRepository'
        ) as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.bulk_update_status_to_listed.side_effect = RuntimeError("db error")
            manager = ListingStatusManager(mock_db, reporter=NullProgressReporter())

            manager.update_statuses_to_listed()

        mock_db.rollback.assert_called_once()
        assert capsys.readouterr().out == ""

    def test_update_statuses_commits_when_no_records_need_update(self):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_asin_family_parent_listing_status_manager.AmzListingLogRepository'
        ) as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.bulk_update_status_to_listed.return_value = 0
            manager = ListingStatusManager(mock_db, reporter=NullProgressReporter())

            manager.update_statuses_to_listed()

        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

    def test_update_statuses_commits_repository_error_sentinel(self):
        mock_db = MagicMock(spec=Session)

        with patch(
            'src.services.amz_asin_family_parent_listing_status_manager.AmzListingLogRepository'
        ) as MockRepository:
            mock_repo = MockRepository.return_value
            mock_repo.bulk_update_status_to_listed.return_value = -1
            manager = ListingStatusManager(mock_db, reporter=NullProgressReporter())

            manager.update_statuses_to_listed()

        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()
