import pytest
import logging
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from src.utils.excel_generator import ExcelGenerator

@pytest.fixture
def mock_workbook():
    wb = MagicMock()
    ws = MagicMock()
    wb.__getitem__.return_value = ws
    ws.max_column = 5
    def cell_side_effect(row, column, value=None):
        cell = MagicMock()
        if row == 4:
            headers = {1: 'SKU', 2: 'Title', 3: 'Bullets', 4: 'Bullets', 5: 'Price'}
            cell.value = headers.get(column)
        return cell
    ws.cell.side_effect = cell_side_effect
    return wb

@pytest.fixture
def generator(mock_workbook):
    # Pass dummy paths
    # We rely on patches during methods to handle exists/mkdir
    with patch('src.utils.excel_generator.ExcelGenerator._find_template_path', return_value=Path("/tmp/templates")), \
         patch('src.utils.excel_generator.ExcelGenerator._find_output_path', return_value=Path("/tmp/output")), \
         patch('pathlib.Path.mkdir'):
        gen = ExcelGenerator()
        return gen

class TestExcelGenerator:
    def test_find_default_paths_from_project_layout(self):
        generator = ExcelGenerator.__new__(ExcelGenerator)

        template_path = generator._find_template_path()
        output_path = generator._find_output_path()

        assert template_path.name == "template_files"
        assert template_path.exists()
        assert output_path.name == "output"

    def test_init_creates_output_dir(self):
        with patch('pathlib.Path.mkdir') as mock_mkdir, \
             patch('src.utils.excel_generator.ExcelGenerator._find_template_path', return_value=Path("t")), \
             patch('src.utils.excel_generator.ExcelGenerator._find_output_path', return_value=Path("o")):
            ExcelGenerator()
            mock_mkdir.assert_called()

    def test_generate_excel_rejects_empty_rows(self, generator):
        import uuid

        with pytest.raises(ValueError, match="rows_data"):
            generator.generate_excel([], 'CABINET', uuid.uuid4())

    def test_generate_excel_success(self, generator, mock_workbook):
        import uuid
        rows = [
            {'SKU': 'SKU-1', 'Title': 'Item 1', 'Price': 10.99},
            {'SKU': 'SKU-2', 'Bullets': ['B1', 'B2']}
        ]
        batch_id = uuid.uuid4()
        
        # Patch load_workbook AND Path.exists for the duration of this test
        with patch('src.utils.excel_generator.openpyxl.load_workbook', return_value=mock_workbook), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.mkdir'): # for skipped mkdir in init? No init already ran.
            
            # We override template_base_path to ensure text match
            generator.template_base_path = Path("/tmp/templates")
            generator.output_base_path = Path("/tmp/output")
            
            output_path = generator.generate_excel(rows, 'CABINET', batch_id)
            
            assert "AmazonUpload_CABINET_" in output_path
            mock_workbook.save.assert_called()

    def test_generate_excel_missing_template(self, generator):
        import uuid
        generator.template_base_path = Path("/tmp/templates")
        
        with patch('pathlib.Path.exists', return_value=False):
            with pytest.raises(FileNotFoundError):
                generator.generate_excel([{}], 'MISSING', uuid.uuid4())

    def test_generate_excel_reraises_save_errors(self, generator, mock_workbook):
        import uuid

        mock_workbook.save.side_effect = RuntimeError("cannot save")
        generator.template_base_path = Path("/tmp/templates")
        generator.output_base_path = Path("/tmp/output")

        with patch('src.utils.excel_generator.openpyxl.load_workbook', return_value=mock_workbook), \
             patch('pathlib.Path.exists', return_value=True):
            with pytest.raises(RuntimeError, match="cannot save"):
                generator.generate_excel([{'SKU': 'SKU-1'}], 'CABINET', uuid.uuid4())

    def test_parse_header_groups_duplicate_headers_and_skips_empty(self, generator, mock_workbook):
        ws = mock_workbook["Template"]

        header_map = generator._parse_header(ws, 4)

        assert header_map == {
            'SKU': [1],
            'Title': [2],
            'Bullets': [3, 4],
            'Price': [5],
        }

    def test_fill_data_logic(self, generator, mock_workbook):
        ws = mock_workbook["Template"]
        header_map = {'SKU': [1], 'Bullets': [3, 4]}
        rows = [{'SKU': 'S1', 'Bullets': ['b1', 'b2', 'b3']}]
        
        generator._fill_data(ws, rows, header_map, 7)
        
        # Checking calls manually
        # Should call cell for S1, b1, b2. b3 ignored.
        calls = ws.cell.mock_calls
        # filter only calls with value=...
        
        # Simple check: b3 should NOT be in any call args
        for c in calls:
            if 'value' in c.kwargs:
                assert c.kwargs['value'] != 'b3'
            if len(c.args) >= 3:
                assert c.args[2] != 'b3'

    def test_fill_data_logs_missing_special_fields(self, generator, mock_workbook, caplog):
        ws = mock_workbook["Template"]
        rows = [{
            'SKU': 'S1',
            'Parent SKU': 'PARENT-1',
            'Variation Theme Name': 'Color',
            'Unknown Field': 'ignored',
        }]

        with caplog.at_level(logging.WARNING, logger='src.utils.excel_generator'):
            generator._fill_data(ws, rows, {'SKU': [1]}, 7)

        assert "应写入字段 Parent SKU" in caplog.text
        assert "应写入字段 Variation Theme Name" in caplog.text
        assert "Unknown Field" not in caplog.text
