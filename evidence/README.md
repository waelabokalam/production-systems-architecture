# Evidence map

The case studies combine inspected source behavior, documented delivery milestones and new local verification runs. Each is labeled separately.

| System | Source reviewed | Evidence category |
|---|---|---|
| TQEN | Restaurant rule/extraction modules, invoice-worker documentation, SSE adapter and Haystack pipeline | Source inspection; 108-test delivery milestone; new frontend run |
| ATG | Six-role enums/permissions, workflow snapshot API, role/RLS architecture and delivery/acceptance records | Source inspection; 54-table/30-migration/15-function baseline; documented 508 backend assertions and 93/93 package baseline; new package runs |
| Crave It | Authorized private source snapshot: locale/planner, role helpers, subscription/kitchen operations, RLS migrations and Worker entrypoint | Source inspection; new focused pure-module checks |
| ClinicalBridge | Public orchestrator, stress definitions, saved outputs and evaluation report | Existing 5/5 and 15/15 evaluated results, with manual review; saved output pairs inspected |
| Fraud MLOps | Public training and prediction code plus CI fixtures | Existing held-out metrics; new lightweight fixture run |
| Nexus AI Workspace | Public default-branch frontend source | New parser/proxy/session fixture run |

## Reproducible public source anchors

- [ClinicalBridge](https://github.com/waelabokalam/clinicalbridge): orchestration, stress cases and saved evaluation outputs.
- [Fraud MLOps at the inspected commit](https://github.com/waelabokalam/fraud-mlops/tree/c86ab381a21503cbdc59f8a3fa54c669c1455323).
- [Nexus AI Workspace at the inspected commit](https://github.com/waelabokalam/Nexus-ai-workspace/tree/370ffd3d343dfa3fb44e0b1fade163886e35c797).

Private source was inspected locally and is retained privately. Test counts apply to the named suites and snapshots, not to arbitrary later releases. The [verification record](verification-2026-11-01.md) contains aggregate output only.
