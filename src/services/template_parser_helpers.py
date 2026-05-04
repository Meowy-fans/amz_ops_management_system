"""Pure helpers for Amazon template workbook parsing."""
from typing import Any, Dict, List, Optional, Tuple


HEADER_VARIATIONS = {
    "group": ["Group Name"],
    "field_name": ["Field Name"],
    "local_label": ["Local Label Name", "Local Label"],
    "accepted_values": ["Accepted Values"],
    "example": ["Example"],
    "required_parent": ["Required for Parent?", "Required for Parant?"],
    "required_child": ["Required for Child?"],
    "required_single": [
        "Required for single SKU product?",
        "Required for single SKU",
    ],
}

REQUIRED_DATA_DEFINITION_HEADERS = {"Field Name", "Local Label Name"}
DEPRECATED_TERMS = ["deprecated", "do not use", "obsolete"]


def find_data_definition_header(sheet, max_scan_rows: int = 5) -> Tuple[int, List[str]]:
    """Find the Data Definitions header row and return its 1-based index."""
    for row_idx in range(1, max_scan_rows + 1):
        if row_idx > sheet.max_row:
            break

        current_row_values = {
            str(cell.value).strip()
            for cell in sheet[row_idx]
            if cell.value
        }

        if REQUIRED_DATA_DEFINITION_HEADERS.issubset(current_row_values):
            raw_headers = [
                str(cell.value).strip() if cell.value else ""
                for cell in sheet[row_idx]
            ]
            return row_idx, raw_headers

    return -1, []


def build_data_definition_column_mapping(raw_headers: List[str]) -> Dict[str, int]:
    """Map canonical Data Definitions column names to worksheet indexes."""
    column_mapping = {}
    for key, variations in HEADER_VARIATIONS.items():
        for variation in variations:
            try:
                column_mapping[key] = raw_headers.index(variation)
                break
            except ValueError:
                continue

    return column_mapping


def extract_field_definitions(sheet, header_row_idx: int, column_mapping: Dict[str, int]) -> Dict[str, Any]:
    """Extract field definitions from Data Definitions rows."""
    field_definitions = {}
    current_group = ""

    for row_idx in range(header_row_idx + 1, sheet.max_row + 1):
        row_values = [cell.value for cell in sheet[row_idx]]
        if not any(v is not None for v in row_values):
            continue

        group_name_idx = column_mapping.get("group", -1)
        group_name = (
            str(row_values[group_name_idx]).strip()
            if group_name_idx != -1 and row_values[group_name_idx]
            else ""
        )

        field_name_idx = column_mapping["field_name"]
        field_name = (
            str(row_values[field_name_idx]).strip()
            if row_values[field_name_idx]
            else ""
        )

        if group_name and not field_name:
            current_group = group_name
            continue

        if field_name and field_name.lower() != "field name":
            field_def = {
                "group": current_group,
                "field_name": field_name,
            }

            for key, idx in column_mapping.items():
                if key not in field_def and idx < len(row_values):
                    field_def[key] = (
                        str(row_values[idx])
                        if row_values[idx] is not None
                        else ""
                    )

            field_definitions[field_name] = field_def

    return field_definitions


def parse_valid_value_declaration(attr_declaration: str) -> Tuple[str, str]:
    """Parse an Amazon valid-value attribute declaration."""
    try:
        attr_name_part, scope_part = attr_declaration.rsplit("[", 1)
        scope = scope_part.split("]", 1)[0].strip()
        attr_name = attr_name_part.strip().rstrip("-").strip()
    except ValueError:
        attr_name = attr_declaration
        scope = "UNKNOWN"

    return attr_name, scope


def is_deprecated(value: str, skip_deprecated: bool = True) -> bool:
    """Return whether a valid value is marked as deprecated."""
    if not skip_deprecated:
        return False

    value_lower = value.lower()
    return any(term in value_lower for term in DEPRECATED_TERMS)


def extract_valid_values(sheet, skip_deprecated: bool = True) -> List[Dict[str, Any]]:
    """Extract Valid Values rows from a template worksheet."""
    valid_values = []
    current_group: Optional[str] = None

    for row_idx in range(1, sheet.max_row + 1):
        row = [
            str(cell.value).strip() if cell.value else ""
            for cell in sheet[row_idx]
        ]
        if not any(row):
            continue

        if row[0]:
            current_group = row[0]
            continue

        if row[1] and "[" in row[1] and "]" in row[1]:
            attr_name, scope = parse_valid_value_declaration(row[1])
            values = [
                value
                for value in row[2:]
                if value and not is_deprecated(value, skip_deprecated)
            ]

            if values:
                valid_values.append({
                    "group": current_group,
                    "attribute": attr_name,
                    "scope": scope,
                    "values": values,
                })

    return valid_values
