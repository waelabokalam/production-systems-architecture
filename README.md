# Production Systems: Architecture & Engineering Case Studies

**AI-assisted products with deterministic operational boundaries, scoped access, and testable failure behavior.**

I'm [Mhd Wael Abo Kalam](https://github.com/waelabokalam). I independently built TQEN and Crave It and delivered ATG's mobile operations platform for a client. This repository makes the engineering behind that work inspectable while keeping commercial source and customer data private.

## Start here

| System | Product | What to inspect |
|---|---|---|
| **[TQEN](case-studies/tqen.md)** | [Live restaurant intelligence and public AI agents](https://tqentech.com) | OCR-to-review boundary; exact-match rules; tenant/branch authorization; Haystack/Qdrant routing and SSE events |
| **[ATG](case-studies/atg.md)** | Six-role logistics mobile app and Administration web | Immutable shipment snapshots; RLS and Client-safe projections; private evidence; transactional notification outbox |
| **[Crave It](case-studies/crave-it.md)** | [Live English/Arabic kitchen and subscription platform](https://craveitsyria.com) | Bilingual ordering; request approval; service-day preparation; kitchen and delivery states; owner/kitchen separation |

## Proof at a glance

| Evidence | Scope |
|---|---|
| TQEN: **108 automated tests** | Documented project delivery milestone; current frontend run: **109 passed, 2 skipped**, excluding the live-service test file |
| ATG: **54 RLS-protected tables, 30 migrations, 15 Edge Functions** | Documented delivery baseline; public diagrams group the schema by responsibility instead of exporting commercial DDL |
| ATG: **508 backend acceptance assertions; 93/93 package tests** | Separate documented acceptance and package/workflow results; current local package run: **57 shared-types + 38 API-client = 95 passed** |
| Crave It: **11 focused checks passed** | Current local localization, delivery-time and plan-request checks, using bundled pure modules |

See [dated test-runner summaries](evidence/verification-2026-11-01.md) and [evidence provenance](evidence/README.md) for commands, scope and what each result demonstrates.

## Engineering decisions

- **AI extracts and synthesizes; application rules authorize and commit.** A plausible model response is not a permission check, an invoice match or a completed operation.
- **UI visibility is a convenience; server and database boundaries enforce access.** TQEN uses organization/branch membership; ATG uses role, assignment and case scope; Crave It separates owner and kitchen capabilities.
- **Corrections are workflows.** Review, rejection, rework and state history are part of the model rather than ad hoc edits.
- **A test count has a scope.** Package contracts, provider-free frontend tests, database policies and physical-device behavior are distinct verification layers.

## Run the public boundary examples

The small Python examples are newly written executable specifications distilled from the inspected behavior, with synthetic values. They illustrate decisions without reproducing commercial implementations.

```bash
python3 -m unittest discover -s tests -v
```

Read [the boundary examples](examples/boundary_contracts.py), [their checks](tests/test_boundary_contracts.py), and the [sanitization notes](SANITIZATION.md).

## New: runnable MCP boundary and local tracing proof

- **[TQEN read-only MCP tools](case-studies/tqen-mcp-tool.md)**: an official-SDK stdio server, strict JSON schemas, server-bound tenant/branch scope, deterministic invoice previews, inert injection-like source text and real protocol regression tests. Synthetic fixtures; no live database writes or model key.
- **[ClinicalBridge OpenTelemetry proof](case-studies/clinicalbridge-tracing.md)**: locally tested orchestration/retrieval spans with parent-child relationships and no clinical payloads in exported telemetry, plus a reviewable patch against the public academic prototype.

Install the optional pinned proof dependencies with `python -m pip install -r requirements-proof.txt`, then run `python -m pytest -q -p no:cacheprovider proof_tests`. The original standard-library suite remains independent of those dependencies.

The [CI workflow](.github/workflows/verify.yml) runs the same standard-library suite without credentials or external services. Its first hosted result will be available after publication.

## More public engineering work

- [ClinicalBridge](https://github.com/waelabokalam/clinicalbridge): multi-agent triage, RAG, deterministic critical bypass, and evaluated failure cases.
- [Fraud MLOps](https://github.com/waelabokalam/fraud-mlops): training-only SMOTE, MLflow experiment tracking and FastAPI serving.
- [Nexus AI Workspace](https://github.com/waelabokalam/Nexus-ai-workspace): stream-driven AI frontend, parser and proxy contracts.

[LinkedIn](https://www.linkedin.com/in/wael-abokalam-500390329/) · [Contact](mailto:wael.bt2@gmail.com)
