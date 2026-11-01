"""Regenerate the sanitized MCP case study from actual code, schemas and tests."""
import json
from pathlib import Path
import subprocess
import sys

from examples.tqen_mcp import tool_schemas


ROOT = Path(__file__).resolve().parents[1]


def main():
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "proof_tests/test_tqen_mcp.py"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    transcript = "$ python -m pytest -q -p no:cacheprovider proof_tests/test_tqen_mcp.py\n" + result.stdout + result.stderr
    schemas = json.dumps([t.model_dump(mode="json", exclude_none=True) for t in tool_schemas()], indent=2)
    source = (ROOT / "examples/tqen_mcp.py").read_text()
    (ROOT / "evidence/tqen-mcp-test-transcript.txt").write_text(transcript)
    (ROOT / "examples/tqen-mcp-tools.schema.json").write_text(schemas + "\n")
    report = """# TQEN: tenant-scoped, read-only MCP invoice and retrieval tools

**Runnable reference implementation | Synthetic fixtures | Official MCP Python SDK**

The MCP boundary exposes deterministic supplier-invoice review and bounded context retrieval without a write path. It distills TQEN's inspected invoice-review design into a public, synthetic implementation; the MCP wrapper is locally tested, not a claim about the live product's deployment.

## Architecture

```mermaid
flowchart LR
    A[Trusted local launcher] --> B[Bound tenant + branch + capabilities]
    C[MCP client / model] --> D[Strict tool arguments]
    B --> E[Read-only boundary]
    D --> E
    E --> F[Composite-scope lookup before return]
    F --> G[Immutable synthetic fixtures]
    G --> H[Preview + untrusted source_text]
    H --> C
```

- `invoice_review`: exact item identity and Decimal arithmetic preview. Confirmation remains a human/application workflow.
- `retrieve_supplier_context`: literal bounded search restricted to the principal's tenant and branch before content is returned.
- Scope comes from the server constructor, never a caller-supplied `tenant_id`, role, branch, URL or SQL argument. Missing capability or scope fails closed.
- An invoice identifier collision cannot select another tenant's invoice. Missing, foreign-tenant and foreign-branch IDs receive the same application error.
- Invoice descriptions and retrieved excerpts remain explicitly labelled untrusted data. No LLM, shell, arbitrary URL fetch, sampling callback or write capability consumes those strings.
- Tool annotations advertise read-only/idempotent/closed-world behavior; the implementation enforces it through immutable fixtures and the absence of mutation interfaces. Annotations alone are not authorization.

## Run and verify

```sh
python3 -m venv .venv-proof
.venv-proof/bin/python -m pip install -r requirements-proof.txt
.venv-proof/bin/python -m pytest -q -p no:cacheprovider proof_tests
.venv-proof/bin/python -m examples.tqen_mcp
```

The server speaks local stdio JSON-RPC. Its trusted demo launcher binds `tenant-a` / `branch-1`; the MCP client cannot change it. No HTTP endpoint, model key or environment variable is needed. A production adapter must construct a principal from verified authentication and propagate it into scoped database/RLS access; the synthetic tests do not certify that unbuilt adapter.

The integration test starts a real SDK client and server subprocess, performs initialize, lists tools, invokes both tools, and verifies invalid arguments, foreign-scope IDs, injected scope, unknown mutation tools and instruction-like invoice text. Other checks cover strict types/limits, capability denial, same-ID collisions, branch isolation and immutable state.

Regenerate this page, schema and transcript using `python -m examples.export_mcp_proof`. The pinned `mcp==1.30.0` maintenance-line API is documented in the [official v1 SDK guide](https://py.sdk.modelcontextprotocol.io/v1/low-level-server/); it is deliberately pinned rather than assuming v2 compatibility.

## Actual passing test transcript

```text
""" + transcript.rstrip() + "\n```\n\n## Actual tool JSON schemas\n\n```json\n" + schemas + "\n```\n\n## Sanitized executable code\n\n```python\n" + source.rstrip() + "\n```\n"
    (ROOT / "case-studies/tqen-mcp-tool.md").write_text(report)
    print(result.stdout.strip())
    print("Generated case study, schemas and test transcript from the passing run.")


if __name__ == "__main__":
    main()
