import pytest
from unittest.mock import MagicMock, patch, mock_open
from sqlalchemy.orm import Session
from src.services.amz_template_management_service import TemplateManagementService
from src.services.progress_reporter import NullProgressReporter

class TestTemplateManagementService:
    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_repo(self):
        with patch('src.services.amz_template_management_service.AmzTemplateRepository') as MockRepo:
            yield MockRepo.return_value

    @pytest.fixture
    def service(self, mock_db, mock_repo):
        return TemplateManagementService(mock_db)

    @patch('src.services.amz_template_management_service.AdvancedTemplateParser')
    @patch('builtins.input', return_value="")
    def test_update_template_from_file_success(self, mock_input, MockParser, service, mock_repo):
        # Mock Parser
        mock_parser_instance = MockParser.return_value
        mock_parser_instance.parse.return_value = (True, "Parsed")
        mock_parser_instance.get_results.return_value = {"fields": ["Color", "Size"]}
        mock_parser_instance.get_all_variation_themes.return_value = ["Color", "Size"]
        
        # Mock Repo save
        mock_repo.save_parsed_data.return_value = 123
        
        # Mock file existence
        with patch('os.path.exists', return_value=True):
            success, msg = service.update_template_from_file("template.xlsx", "CATEGORY")
            
            assert success is True
            assert "ID: 123" in msg
            mock_parser_instance.parse.assert_called_once()
            mock_repo.save_parsed_data.assert_called_once()

    @patch('src.services.amz_template_management_service.AdvancedTemplateParser')
    @patch('builtins.input', return_value="")
    def test_update_template_from_file_parse_fail(self, mock_input, MockParser, service):
        mock_parser_instance = MockParser.return_value
        mock_parser_instance.parse.return_value = (False, "Invalid Format")
        
        with patch('os.path.exists', return_value=True):
            success, msg = service.update_template_from_file("template.xlsx", "CATEGORY")
            
            assert success is False
            assert "Invalid Format" in msg

    @patch('src.services.amz_template_rule_correction.openpyxl')
    def test_correct_rules_from_report_success(self, mock_openpyxl, service, mock_repo):
        # Mock Workbook
        mock_wb = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb
        mock_wb.sheetnames = ["Feed Processing Summary"]
        
        mock_sheet = MagicMock()
        mock_wb.__getitem__.return_value = mock_sheet
        
        # Mock Header Row (row 1)
        mock_sheet.__getitem__.side_effect = lambda idx: (
            [MagicMock(value="Error code"), MagicMock(value="Error message")] if idx == 1 else []
        )
        
        # Mock Data Rows
        # iter_rows should return rows with Error code 90220 and message
        row1 = [MagicMock(value="90220"), MagicMock(value="'brand_name' is required but not supplied.")]
        mock_sheet.iter_rows.return_value = [row1]
        
        # Mock DB definition
        mock_repo.find_latest_template_id_and_defs.return_value = (
            1, 
            {"brand_name_key": {"local_label": "brand_name", "required_child": "Optional"}}
        )
        mock_repo.update_field_definitions_by_id.return_value = True
        
        with patch('os.path.exists', return_value=True):
            success, msg = service.correct_rules_from_report("report.xlsm", "CATEGORY")
            
            assert success is True
            assert "brand_name" in msg
            mock_repo.update_field_definitions_by_id.assert_called_once()

    def test_determine_priority_themes_default(self, service, mock_repo):
        # Mock input to return empty (skip)
        with patch('builtins.input', return_value=""):
            mock_repo.find_latest_priority_themes_by_category.return_value = None
            
            themes = service._determine_priority_themes("CAT")
            assert themes == ["COLOR/SIZE", "COLOR", "SIZE", "MATERIAL", "STYLE", "COLOR/STYLE"]

    def test_determine_priority_themes_user_input(self, service):
        with patch('builtins.input', return_value=" Color, Size "):
            themes = service._determine_priority_themes("CAT")
            assert themes == ["COLOR", "SIZE"]

    def test_determine_priority_themes_with_null_reporter_does_not_print(
        self,
        mock_db,
        mock_repo,
        capsys
    ):
        service = TemplateManagementService(mock_db, reporter=NullProgressReporter())
        service.repo = mock_repo
        mock_repo.find_latest_priority_themes_by_category.return_value = None

        with patch('builtins.input', return_value=""):
            themes = service._determine_priority_themes("CAT")

        assert themes == ["COLOR/SIZE", "COLOR", "SIZE", "MATERIAL", "STYLE", "COLOR/STYLE"]
        assert capsys.readouterr().out == ""

    def test_correct_rules_from_report_with_null_reporter_does_not_print(
        self,
        mock_db,
        mock_repo,
        capsys
    ):
        service = TemplateManagementService(mock_db, reporter=NullProgressReporter())
        service.repo = mock_repo
        service._parse_report_for_required_fields = MagicMock(return_value=set())

        success, msg = service.correct_rules_from_report("report.xlsm", "CAT")

        assert success is True
        assert "无需矫正" in msg
        assert capsys.readouterr().out == ""
