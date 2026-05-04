# Template Mapping Module Design

## Status

- Contract status: Draft
- Implementation status: Existing behavior documented, no behavior change in this document
- Owner modules:
  - `src/services/amz_template_parser.py`
  - `src/services/amz_template_management_service.py`
  - `src/utils/data_mapping_helper.py`
  - `src/utils/excel_generator.py`
  - `src/utils/variation_helper.py`

## Responsibility

Template and mapping modules transform local product data into Amazon template rows and write `.xlsm` upload files.

## Components

### `AdvancedTemplateParser`

Parses Amazon category workbook sheets and extracts template fields, data definitions, valid values, and variation metadata.

### `TemplateManagementService`

Coordinates template parsing, template persistence, and template correction from Amazon error reports.

### `DataMappingHelper`

Maps product data to Amazon fields using `config/amz_listing_data_mapping/amz_mapping.json`.

Supported mapping styles include:

- static values
- direct fields
- database fields
- JSON path extraction
- unit conversion
- category lookup
- optional LLM-enhanced fields

### `VariationHelper`

Groups SKUs into single products and variation families using relation graph connected components.

### `ExcelGenerator`

Loads category workbook templates and writes generated rows to the Amazon upload sheet.

## Current Deviations To Mitigate

- Mapping configuration is file-based and loaded inside helpers; the effective schema is not documented as a formal JSON Schema.
- `DataMappingHelper` is over 500 lines and should be split after behavior is better covered by tests.
- Template parsing and correction behavior is only lightly tested.
- Some parser paths log and print together.
- Generated file path and template lookup rules are implicit.

## Acceptance Baseline

- Existing Excel generator and variation helper tests must remain green.
- Existing generated workbook format must remain compatible with Amazon upload templates.
- Any future mapping schema change must be documented in `docs/api-contracts/`.
