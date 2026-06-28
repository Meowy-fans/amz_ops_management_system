# Listing Payload Engine V2 LIVE Canary Readiness - 2026-06-27

## Decision: **NOT READY** for `--engine v2 --no-dry-run`

V2 is now in the production image and dry-run gates are green, but LIVE PUT
canary should remain blocked until the items below are explicitly signed off.

## Satisfied Preconditions

| Gate | Status | Evidence |
| --- | --- | --- |
| Shadow/regression go for CABINET/HOME_MIRROR/OTTOMAN | ✅ | `evaluate-listing-v2-regression` |
| V2 authoritative dry-run canary | ✅ | `docs/test-reports/2026-06-27-listing-payload-v2-authoritative-canary.md` |
| V2 review resume smoke | ✅ | SOFA `meow251108Bg4d4` |
| `ValidationPreviewV2.compare()` gate | ✅ | `evaluate-listing-v2-validation-compare` go 3/3 |
| V2 code in production image | ✅ | `2026-06-27-listing-payload-v2` deployed |
| Production container validation compare | ✅ | In-container `go` without workspace mount |
| Non-existing create-path preview | ✅ (partial) | OTTOMAN new parent `PARENT-B44F29098D69` passed |
| `--engine v2 --no-dry-run` blocked | ✅ | CLI/service guardrail verified |

## Remaining Blockers Before LIVE Canary

1. **Single-SKU CABINET/HOME_MIRROR non-existing pool is thin** — most candidate
   SKUs now return `skipped_existing_scope`. Need a fresh SKU batch or a
   controlled new-listing pilot SKU before LIVE PUT.
2. **No staged LIVE canary plan** — cutover doc still requires single category /
   single SKU scope with rollback and observation window.
3. **V1 `@retire` not started** — intentional; parity observation period not
   complete.
4. **`operation_handlers.py` still 1432 lines** — operational debt, not a hard
   blocker but should be tracked.

## Recommended Next Slice

1. Pick one **confirmed not-on-Amazon** SKU per live-eligible category
   (`CABINET`, `HOME_MIRROR`) and run
   `generate-listing-api --engine v2 --strict-validation --only-not-on-amazon`.
2. Draft a **LIVE canary runbook**: one SKU, manual approval, 24h watch, instant
   rollback to V1 engine.
3. Only after (1)+(2), consider unblocking `--engine v2 --no-dry-run` behind an
   env flag such as `LISTING_V2_LIVE_CANARY_SKUS`.

## Explicit Prohibitions (unchanged)

- Do not enable global `LISTING_PAYLOAD_ENGINE=v2` for all LIVE PUT traffic.
- Do not add `@retire` to V1 resolver/renderer/coverage yet.
