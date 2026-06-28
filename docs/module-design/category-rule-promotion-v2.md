# Category Rule Promotion V2 (S10)

> Module: `src/services/category_rule_promotion_v2.py`
> Slice: S10 go-live promotion gate

## Responsibility

Evaluate a promotion checklist before setting category YAML `mode: live_eligible`.
Creates a timestamped YAML backup on write and records a `promoted` audit row.

## CLI

```bash
python3 main.py --task promote-category-rules-v2 --category TABLE --no-dry-run \
  --reviewer operator@example

# Optional: require preview KPI from live re-run or acceptance JSON
python3 main.py --task promote-category-rules-v2 --category BED_FRAME \
  --require-preview --min-preview-passed 1 \
  --acceptance-file docs/test-reports/s7-bed-frame.json --no-dry-run
```

## Checklist (v1)

| Check | Required | Source |
| --- | --- | --- |
| `mode_is_dry_run` | yes (unless already live) | YAML loader |
| `review_blocking_clear` | yes | S9 `RuleReviewServiceV2` |
| `s7_offline_zero_missing` | yes | Re-run or `--acceptance-file` |
| `s7_preview_min_passed` | only with `--require-preview` | Re-run or acceptance file |
| `golden_regression` | yes for golden categories only | S6 `RuleMigrationV2` |

## Idempotency

If category is already `live_eligible`, promotion returns `already_live_eligible`
without modifying YAML.

## Audit

Uses `amz_listing_pending_rule_review` with:
`path_key=(root)`, `issue_type=promoted`, `decision=promoted`.
