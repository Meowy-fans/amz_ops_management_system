# Rule Review Service V2 (Layer 1)

> Module: `src/services/rule_review_service_v2.py`
> Repository: `src/repositories/pending_rule_review_repository.py`
> Slice: S5 (scan) / S9 (approve) / S12 (`risk_partial_emit`)

## Responsibility

Scan category YAML attribute rules for Layer 1 review gaps, persist operator
decisions, and write approved patches back to authoritative YAML.

## CLI

```bash
python3 main.py --task review-pending-rules --category BED_FRAME
python3 main.py --task approve-rule --category BED_FRAME \
  --path-key number_of_items --decision safe_default \
  --reviewer operator@example --no-dry-run
```

## Decisions

| Decision | YAML effect |
| --- | --- |
| `safe_default` | Mark default sources with `safe_default: true` |
| `manual_review` | Set `layer1_review.route: manual` on leaf |
| `omit_attribute` | Remove rule node / root attribute block |
| `coverage_ignore` | Append root to `coverage_ignore_required`, remove attribute block |
| `waived` | Audit only; suppress re-report of issue |

## Blocking vs info

Blocking issue types (promote gate): `todo_placeholder`, `unsafe_default`,
`structural_parent_sources`, `missing_dimension_strategy`, `risk_partial_emit`.

Non-blocking: `inherited_source`.

## Persistence

Table `amz_listing_pending_rule_review` (migration `013_amz_listing_pending_rule_review`).
Unique key: `(category, path_key, issue_type)`.

## S12 integration

Review scan emits `risk_partial_emit` when a root listed in
`coverage_ignore_required` still has an `attributes.*` block. Runtime guard lives
in `optional_rule_children_enricher_v2.py` (skip enrich) and
`listing_payload_engine_v2.py` (post-compose strip).
