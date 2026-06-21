# ADR-2026-06-15: Block CABINET 48in Vanity LIVE Submission On Width Warning

**日期**: 2026-06-15
**状态**: Accepted

## Context

The CABINET 18-SKU strict dry-run reached Amazon `VALIDATION_PREVIEW` with code-level issues resolved, but the 48in vanity plans still received Amazon `100335` warnings because CABINET `item_depth_width_height.width` exceeded the observed 42in max for that product type. The affected payloads used package/combo widths around 52.76in and 53.54in.

The Epic goal is API-native multi-category listing with accurate attributes and low operational noise. Forcing LIVE submission through a product type that Amazon warns is out of range would create listing-quality risk and make future category scaling harder.

## Decision

We will allow CABINET 48in vanity SKUs to run strict dry-run and Amazon `VALIDATION_PREVIEW`, but we will block LIVE `putListingsItem` when the local quality gate emits `ISSUE_DERIVED_DIMENSION_RANGE` for CABINET width over 42in.

We will keep this as configuration-driven behavior in `config/listing_gates/quality_gate.yaml` with `live_blocking: true`, not as a SKU hardcode. The unblock path is either:

1. Confirm a better Amazon product type and move the SKU/category mapping plus attribute rules to that product type.
2. Confirm through Amazon/vendor evidence that CABINET is still the correct product type and update the configured threshold with documented evidence.

Duplicate variation signatures remain fail-closed through the variation resolver. The default action is to keep those SKUs blocked until the family relationship is split, attributes are corrected, or the SKU is intentionally listed as single.

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| Submit CABINET LIVE despite warning | Fastest path to attempt listing | Carries known product-type quality risk and may create suppressed/low-quality listings | Conflicts with API-native quality gate objective |
| Hardcode affected SKUs as blocked | Simple immediate control | Does not scale and violates multi-category design direction | Replaced by config-driven issue-derived gate |
| Change all 48in vanity SKUs to another product type immediately | Potentially fixes width schema fit | Requires Product Type Discovery and attribute-rule validation before LIVE | Kept as the recommended unblock path, not assumed without validation |
| Treat width warning as blocking in all dry-runs | Prevents any Amazon preview call | Loses authoritative Amazon issue collection during strict dry-run | We still need strict dry-run feedback for evidence |

## Consequences

**正面**: LIVE publishing cannot proceed when Amazon has already signaled CABINET width mismatch; strict dry-run remains useful for evidence and regression reports.

**中性**: CABINET 48in vanity listings need one extra category/product-type decision before LIVE.

**负面**: Some otherwise valid plans remain blocked until product type discovery or documented threshold adjustment is completed.

## References

- `docs/test-reports/2026-06-14-cabinet-18-strict-dry-run.md`
- `config/listing_gates/quality_gate.yaml`
