# Category Onboarding V2 — Operator Runbook

Standard path for adding a **new** Amazon product type to Rule Authoring V2.

## Prerequisites

- Product type schema cached in DB (`AmazonSchemaService.get_cached_schema`)
- At least one pending pool SKU mapped to the category
- Reference category optional (e.g. `TABLE` for furniture)

## 1. Onboard (generate + map + review + acceptance)

```bash
python3 main.py --task onboard-category-v2 --category <NEW_CATEGORY> \
  --reference TABLE \
  --sample-skus 4 \
  --run-s7-offline \
  --overwrite
```

Optional Amazon preview gate data:

```bash
python3 main.py --task onboard-category-v2 --category <NEW_CATEGORY> \
  --reference TABLE --run-s7-offline --run-s7-preview --overwrite
```

**Outputs**

| Artifact | Location |
| --- | --- |
| Rule YAML | `config/.../api_attribute_rules/{category}.yaml` |
| State | `config/.../category_rule_state/{category}.json` |
| Acceptance | `docs/test-reports/{date}-{category}-onboard-acceptance.json` |

## 2. Operator patches (manual, documented)

Before promote, review YAML for category-specific patterns:

- GTIN exemption / `merchant_suggested_asin` → `coverage_ignore_required` only (no attribute block)
- `dimension_strategy` (`item_depth_width_height` vs `item_length_width_height`)
- Category defaults not inferrable from reference reuse

```bash
python3 main.py --task review-pending-rules --category <NEW_CATEGORY>
```

## 3. Approve Layer 1 items

```bash
python3 main.py --task approve-rule --category <NEW_CATEGORY> \
  --path-key <path_key> --decision safe_default \
  --reviewer <you> --no-dry-run
```

Decisions: `safe_default` | `manual_review` | `omit_attribute` | `coverage_ignore` | `waived`

## 4. S7 acceptance (if not run during onboard)

```bash
python3 scripts/s7_rule_authoring_acceptance.py --preview <NEW_CATEGORY>
```

## 5. Promote to live_eligible

```bash
python3 main.py --task promote-category-rules-v2 --category <NEW_CATEGORY> \
  --require-preview --min-preview-passed 1 \
  --acceptance-file docs/test-reports/<acceptance>.json \
  --no-dry-run --reviewer <you>
```

## 6. Ongoing feedback (rule layer only)

```bash
python3 main.py --task analyze-listing-feedback-v2 --category <NEW_CATEGORY>
python3 main.py --task learn-rules-from-feedback-v2 --category <NEW_CATEGORY>  # dry-run default
python3 main.py --task approve-rule ...  # required before non-placeholder YAML changes
```

**Out of scope:** HTML/content issues (100339) → content pipeline, not this runbook.

## See also

- Module design: `docs/module-design/category-onboarding-v2.md`
- Epic runbook: `docs/epics/listing-rule-authoring-v2.md` §7
