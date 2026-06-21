# ADR-2026-06-22: Unified Attribute Pipeline

- **Status**: Accepted
- **Date**: 2026-06-22

## Context

API-native listing plans currently receive attribute values from two places:

1. `AmazonListingPayloadBuilder` hardcodes common Amazon attributes.
2. `AttributeResolver` renders product-type YAML rules.

When generated YAML contains low-confidence required rules for the same attributes
that the builder already populated, `AmazonListingAttributeCoverageGate` treats the
resolver result as untrusted and blocks the listing.

## Decision

`AttributeResolver` plus YAML presets are the authoritative source for Amazon
attribute values. `AmazonListingPayloadBuilder` remains responsible for structural
SP-API blocks only: images, offers, inventory, dimensions, variation relationships,
post-processing, and schema allowlist filtering.

YAML source contracts are:

- `path`: read facts from `AmazonListingDraft`.
- `default`: apply an auditable business fallback with confidence and evidence.
- `llm`: extract evidence-bound optional attributes from product facts.
- `transform`: normalize the source value into the expected payload value.

Required attributes resolved from `llm` remain blocking and require manual review.

## Consequences

- Universal listing defaults move into `api_attribute_presets`.
- Product-type YAML can opt into presets and override preset attributes.
- Generated new-category YAML no longer creates `default: null` rules for universal
  required attributes covered by the preset.
- Builder hardcoded business defaults are removed or overridden by YAML-rendered
  values.
