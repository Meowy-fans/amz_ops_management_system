# EPIC: Schema-driven Attribute Resolution Pipeline

> Epic ID: `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`
> Status: Completed
> Date: 2026-06-15
> Completed: 2026-06-15
> Production Deployed: 2026-06-15
> Owner: amz-listing-management-system
> Predecessor: `EPIC-AMZ-LISTING-API-NATIVE-QUALITY` (Completed 2026-06-15)

## 1. Background

After `EPIC-AMZ-LISTING-API-NATIVE-QUALITY` shipped, the 2026-06-15 HOME_MIRROR
acceptance proved that `fabric_type` coverage alone is not enough. A re-run still
returned 15 issues per SKU:

- 10 ERROR `MISSING_REQUIRED_ATTRIBUTE` (Amazon code 90220): Model Name, Frame
  Material, Mounting Type, Required Assembly, Item Shape, Item Width Unit,
  Included Components, Special Features, Room Type, Number of Items.
- 5 WARNING `inapplicable attribute` (Amazon code 90000900): Item Depth, Item
  Type Name, Item Width, item_height, target_audience_base.

Root causes confirmed in code:

1. `AmazonListingPayloadBuilder.build_plan()` writes a hardcoded base attribute
   set for every product type, then removes per-type fields only via YAML
   `remove_attributes`. This blacklist approach leaks inapplicable attributes for
   any product type that has not enumerated its removals (HOME_MIRROR).
2. `AmazonSchemaService.get_required_properties()` returns only the schema
   top-level `required` array. Deep/conditional required attributes are invisible
   to `AmazonListingAttributeCoverageGate`, so the 10 missing required attributes
   are not blocked locally.
3. The LLM extraction layer is documented but not wired. `AttributeResolver`
   only reads `content/product/offer/variation` roots, so attributes that exist
   in the product text but not as structured fields cannot be recovered without
   inventing values.

This is not a HOME_MIRROR bug. It is a pipeline-shape problem that repeats for
every new product type.

## 2. Epic Goal

Make Amazon Product Type Definitions schema the single source of truth for which
attributes a listing must and may contain, resolve every attribute value through
an evidence-driven priority chain, let the LLM extract facts but never invent
them, and let Amazon `VALIDATION_PREVIEW` feedback continuously complete the
required-attribute set — all without per-product-type Python hardcode.

## 3. Design Principles

| Principle | Root cause solved | Meaning |
| --- | --- | --- |
| Schema allowlist | Inapplicable attributes (root cause 1) | Only emit attributes that exist in the product type schema `properties`; drop any other key at render time. Retire per-type `remove_attributes` blacklists. |
| Required set = static deep-scan + preview-learned | Missing required (root cause 2) | Expand required from top-level + nested object + `allOf`/conditional `required`; merge required attributes discovered from Amazon `MISSING_REQUIRED_ATTRIBUTE` feedback. |
| Value must carry evidence + confidence | LLM fabrication risk | Every value (supplier, derived, LLM, default) has `source/evidence/confidence`; required attributes that are low-confidence or evidence-free block LIVE. |

## 4. Resolution Priority (high to low, stop at first hit)

```text
1. Supplier structured fact   (product.attributes.*)         confidence=high
2. Deterministic derivation   (unit/enum/dimension mapping)  confidence=high
3. LLM constrained extraction (find in product text; null if absent) confidence=medium, must quote source
4. Evidenced safe default     (YAML default + evidence)      confidence=medium
5. Unresolved -> manual review queue / required -> block      blocking
```

LLM always sits after facts and before defaults, and may only extract, never
invent.

## 5. LLM Low-fabrication Contract

This is the safety core of the Epic.

1. Extract, do not invent. Input is product title/description/bullets/raw
   attributes plus the target attribute schema definition (including enum). For
   each attribute the LLM returns `{value | null, evidence (source quote),
   confidence}`. If not present in source, it must return `null`.
2. Enum lock. For attributes with a schema `enum`, the LLM may only choose from
   the provided enum, otherwise `null`.
3. Sensitive field blacklist. Brand, identifiers/GTIN, safety/compliance
   declarations (`supplier_declared_*`), material truth claims, and certifications
   never accept LLM defaulting; they come from facts or manual review only.
4. Output re-validation. LLM output is re-checked against schema type/enum;
   empty-evidence values are downgraded to unusable.
5. Confidence ceiling. LLM sourced values are capped at `medium`, so required
   attributes filled by LLM trigger the coverage gate review/warn path instead of
   silently going LIVE.

## 6. In Scope

- `AmazonSchemaService` deep/conditional required extraction and property-name /
  shape inspection helpers.
- `AmazonListingAttributeCoverageGate` consumes the expanded + preview-learned
  required set.
- `ValidationFeedbackStore` persists Amazon preview/PUT/GET issues and feeds
  `MISSING_REQUIRED_ATTRIBUTE` back into the learned required set.
- `AttributePayloadRenderer` schema allowlist filter plus schema-shape rendering
  (single value, list, measure+unit, nested object).
- `LLMAttributeExtractor` constrained extraction wired into `AttributeResolver`
  as priority layer 3, with `llm` source path support.
- `AmazonListingPayloadBuilder` slimming: base/category attributes move to
  resolver/renderer/config; remove category branches (CABINET dimensions,
  `normalize_cabinet_attributes`).
- HOME_MIRROR rule set completion driven by Amazon preview feedback.

## 7. Out of Scope

- New marketplace abstraction beyond Amazon US.
- Image asset processing changes.
- Order, pricing/inventory, PPC, profit, lifecycle modules.
- Web UI redesign (CLI/strict-dry-run-first).
- Replacing the LLM content generation/review gate.

## 8. Work Breakdown

| Task | Title | Phase | Acceptance |
| --- | --- | --- | --- |
| TASK-138 | Schema deep-required extraction + coverage gate upgrade + preview-learned required | Done | Coverage gate uses conservative schema required plus Amazon preview-learned `90220` feedback. |
| TASK-139 | Renderer schema allowlist filter + schema-shape rendering | Done | Inapplicable attributes are dropped generically; measure and object shapes render from config. |
| TASK-140 | LLM constrained attribute extractor in resolver | Done | Resolver supports injected evidence-backed LLM extraction with enum lock, sensitive blacklist, and medium confidence cap. |
| TASK-141 | PayloadBuilder slimming and category hardcode migration | Done | CABINET dimension strategy and schema-shape normalization are selected by YAML; no CABINET branch remains in `AmazonListingPayloadBuilder`. |
| TASK-142 | Epic production deployment + acceptance docs | Done | HOME_MIRROR strict dry-run reached 6/6 `validation_preview_passed` with 0 issues; OTTOMAN smoke passed; CABINET coverage regression closed, with known TASK-134 width warnings remaining. |

## 9. Independent Acceptance Criteria

1. `AmazonSchemaService` exposes an expanded required set covering nested and
   conditional `required`.
2. `AmazonListingAttributeCoverageGate` blocks all HOME_MIRROR missing required
   attributes locally before submitter.
3. Amazon preview `MISSING_REQUIRED_ATTRIBUTE` feedback is persisted and merged
   into the required set on the next run.
4. Renderer drops any attribute not in the product type schema; no listing emits
   inapplicable attributes.
5. Per-type `remove_attributes` blacklist is no longer needed for new categories.
6. `LLMAttributeExtractor` returns `null` for absent facts, is enum-locked, and
   excludes the sensitive field blacklist.
7. LLM-sourced values are capped at `medium` confidence and never silently fill a
   required attribute LIVE.
8. `AmazonListingPayloadBuilder` has no remaining product-type branch.
9. HOME_MIRROR strict dry-run returns `validation_preview_passed` with 0 issues.
10. CABINET and OTTOMAN strict dry-run regressions remain green.
11. Targeted unit/integration tests and full `pytest -q` pass.
12. `STATUS.md`, `TODO.md`, the system design doc, and an acceptance report are
    updated.

## 10. Implementation Decisions

| Decision | Default |
| --- | --- |
| Attribute inclusion policy | Schema allowlist. Builder/renderer emit only schema properties; non-schema keys are dropped. |
| Required completeness source | Static deep-scan first; Amazon preview feedback augments the learned required set over time. |
| LLM role | Extraction only, evidence-bound, enum-locked, sensitive blacklist, capped at `medium`. |
| Default policy | Defaults allowed only with `confidence` and `evidence`; low-confidence required defaults block LIVE. |
| Migration safety | New layers ship behind existing gates; strict dry-run stays the authoritative check before LIVE. |

## 11. Risks

| Risk | Mitigation |
| --- | --- |
| Static deep-scan still misses conditional required. | Keep Amazon `VALIDATION_PREVIEW` as authoritative gate and learn required from feedback. |
| LLM extracts plausible but wrong facts. | Evidence quote requirement, enum lock, sensitive blacklist, medium-confidence cap, coverage gate review. |
| Schema allowlist drops a legitimately accepted non-schema attribute. | Log dropped keys; reconcile against preview WARNING feedback before tightening. |
| Builder slimming regresses CABINET/OTTOMAN. | Migrate per-type behavior to config with regression strict dry-run before removing hardcode. |
| Schema cache stale. | Track schema fetch time/hash; allow forced refresh. |

## 12. Rollback / Safety

- Keep `generate-listing-api` dry-run default; LIVE behind `--no-dry-run`.
- Strict validation preview must not call PUT.
- Migrate category hardcode only after config-driven regression passes.
- Do not remove existing audit tables; add `ValidationFeedbackStore` additively.

## 13. Related Documents

- `docs/decisions/ADR-2026-06-15-schema-driven-attribute-pipeline.md`
- `docs/module-design/api-attribute-resolution.md`
- `docs/api-native-listing-system-design.md`
- `docs/epics/api-native-listing-quality-pipeline.md`
- `docs/test-reports/2026-06-15-required-attribute-coverage-gate.md`
