# Listing Feedback Analyzer V2 (S11)

> Module: `src/services/listing_feedback_analyzer_v2.py`
> Slice: S11 feedback triage

## CLI

```bash
python3 main.py --task analyze-listing-feedback-v2 --category BED_FRAME --limit 50
```

## Triage routes (v1)

| Code / signal | Route | Suggested action |
| --- | --- | --- |
| 90220 | `rule_layer` | learn → YAML placeholder → `approve-rule` |
| 99022 / partial value | `rule_layer` | `omit_attribute` / `coverage_ignore` |
| 90244 / enum | `rule_or_data` | enum source / normalizer review |
| 100339 / HTML | `content_layer` | content pipeline; no auto YAML |
| WARNING | `log_only` | log only |

## Follow-up workflow

```bash
python3 main.py --task learn-required-from-submissions --category BED_FRAME
python3 main.py --task learn-rules-from-feedback-v2 --category BED_FRAME --no-dry-run
python3 main.py --task approve-rule --category BED_FRAME --path-key ... --decision ...
```

Non-placeholder YAML patches still require Layer 1 `approve-rule`.
