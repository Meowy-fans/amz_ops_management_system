import openpyxl

from src.services.amz_template_parser import AdvancedTemplateParser
from src.services.template_parser_helpers import (
    build_data_definition_column_mapping,
    extract_field_definitions,
    extract_valid_values,
    find_data_definition_header,
    is_deprecated,
    parse_valid_value_declaration,
)


def test_data_definition_helpers_find_header_and_extract_grouped_fields():
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "Data Definitions"
    sheet.append(["ignored"])
    sheet.append([
        "Group Name",
        "Field Name",
        "Local Label Name",
        "Accepted Values",
        "Required for Parant?",
    ])
    sheet.append(["Identity", "", "", "", ""])
    sheet.append(["", "brand_name", "Brand", "Free text", "Required"])

    header_row_idx, raw_headers = find_data_definition_header(sheet)
    column_mapping = build_data_definition_column_mapping(raw_headers)
    definitions = extract_field_definitions(sheet, header_row_idx, column_mapping)

    assert header_row_idx == 2
    assert column_mapping["required_parent"] == 4
    assert definitions["brand_name"]["group"] == "Identity"
    assert definitions["brand_name"]["local_label"] == "Brand"
    assert definitions["brand_name"]["required_parent"] == "Required"


def test_valid_value_helpers_parse_scope_and_filter_deprecated_values():
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "Valid Values"
    sheet.append(["Variation", "", "", ""])
    sheet.append(["", "Variation Theme Name [Global]", "Color", "Old Deprecated"])
    sheet.append(["", "Color Name [Global]", "Red", "Do not use Blue"])

    values = extract_valid_values(sheet, skip_deprecated=True)

    assert parse_valid_value_declaration("Color Name - [Global]") == (
        "Color Name",
        "Global",
    )
    assert is_deprecated("obsolete shade")
    assert values == [
        {
            "group": "Variation",
            "attribute": "Variation Theme Name",
            "scope": "Global",
            "values": ["Color"],
        },
        {
            "group": "Variation",
            "attribute": "Color Name",
            "scope": "Global",
            "values": ["Red"],
        },
    ]


def test_advanced_template_parser_parse_minimal_workbook(tmp_path):
    file_path = tmp_path / "template.xlsx"
    wb = openpyxl.Workbook()

    template_sheet = wb.active
    template_sheet.title = "Template"
    template_sheet.cell(row=4, column=1, value="sku")
    template_sheet.cell(row=4, column=2, value="brand_name")

    definitions_sheet = wb.create_sheet("Data Definitions")
    definitions_sheet.append([
        "Group Name",
        "Field Name",
        "Local Label Name",
        "Accepted Values",
        "Required for Parent?",
        "Required for Child?",
    ])
    definitions_sheet.append(["Identity", "", "", "", "", ""])
    definitions_sheet.append(["", "brand_name", "Brand", "Free text", "Required", "Required"])

    valid_values_sheet = wb.create_sheet("Valid Values")
    valid_values_sheet.append(["Variation", "", "", ""])
    valid_values_sheet.append(["", "Variation Theme Name [Global]", "Color", "Size"])

    wb.save(file_path)

    parser = AdvancedTemplateParser(str(file_path))
    success, message = parser.parse()

    assert success is True
    assert message == "解析成功"
    assert parser.get_results()["fields"] == ["sku", "brand_name"]
    assert parser.get_results()["field_definitions"]["brand_name"]["group"] == "Identity"
    assert parser.get_all_variation_themes() == ["Color", "Size"]
