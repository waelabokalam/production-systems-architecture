# Scoped verification — 2026-11-01

The following summaries were transcribed from actual local runs. Filesystem paths, raw payloads, identifiers and machine-specific timing output have been removed. No hosted client database, live OCR service or LLM provider was called for these checks.

## ATG — shared contracts

Command: `vitest run`, from the shared-types package.

```text
Test Files  8 passed (8)
Tests       57 passed (57)
Exit        0
```

Coverage areas: workflow states, schemas, document contracts, error contracts and input normalization.

## ATG — API-client contracts

Command: `vitest run`, from the API-client package.

```text
Test Files  7 passed (7)
Tests       38 passed (38)
Exit        0
```

Coverage areas: task execution, management commands, storage adapters, snapshot commands, assignment/work queues and error mapping. Combined current package result: **95 passed**. The requested **93/93** figure is the earlier documented delivery milestone.

## TQEN — provider-free frontend rules and contracts

Command: `vitest run --exclude '**/*live.test.ts'`, from the inspected frontend checkout.

```text
Test Files  10 passed (10)
Tests       109 passed | 2 skipped (111)
Exit        0
```

Coverage areas: deterministic invoice matching, invoice/price/total anomalies, operational summaries, reputation rules, error handling, proxy boundaries and SSE/session behavior. Two OCR checks require externally supplied provider evidence and were skipped; the live-service test file was excluded. The **108 automated tests** figure is the documented earlier project milestone, not an OCR accuracy percentage.

## Crave It — focused pure-module checks

Commands: bundle the three TypeScript test entrypoints with esbuild, then run the resulting modules using `node --test`.

```text
Tests       11
Pass        11
Fail        0
Skipped     0
Exit        0
```

Inputs: delivery-time normalization, localization/dictionary parity, localized order-message values, pending-only plan-request transitions, owner-only review and snapshot preservation. This is not the build/HTTP/production-RLS suite.

## Public code checks

| Project | Command or inspection | Observed result |
|---|---|---|
| Fraud MLOps | `python -m pytest -q tests` | **4 passed**; lightweight feature-order/risk/action/output fixtures, not an HTTP-model integration run |
| Nexus AI Workspace | `vitest run` on the public source snapshot | **22 passed across 5 files**; demo hub, sales lead, proxy, parser and session contracts |
| ClinicalBridge | Read saved scenario/result pairs without generating new model output | **5 completed pairs**, with **3 designed review checks per scenario**; the project's published evaluation reports 5/5 scenarios and 15/15 failure-mode checks including manual review |

## Public showcase — synthetic boundary specifications

Command: `python3 -m unittest discover -s tests -v`, from this repository.

```text
Ran 17 tests
OK
Exit 0
```

The suite models selected invariants with synthetic values: exact item/unit matching, organization/branch scope, case visibility, active-role checks, review-gated task completion, owner-only request review and Arabic fallback. It does not rerun the commercial applications or execute their database policies.
