"""Record only the public, synthetic proof. Run from the repository root.

python docs/evidence/generate_evidence.py
Requires the already published requirements-proof.txt. No network or model calls.
"""
from dataclasses import asdict
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def capture_spans():
    """Run the portable tracing helper with fixed IDs and real local timings."""
    from examples.clinicalbridge_tracing import LocalTracing, trace_operation
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.id_generator import IdGenerator

    class FixedIds(IdGenerator):
        """Stable identifiers for this offline fixture; never use in deployment."""
        def __init__(self):
            self.next_span_id = 0
            self.next_trace_id = 0

        def generate_span_id(self):
            self.next_span_id += 1
            return self.next_span_id

        def generate_trace_id(self):
            self.next_trace_id += 1
            return self.next_trace_id

    @trace_operation("ehr_retrieval")
    def retrieve():
        return ["synthetic fixture"]

    @trace_operation("agent_attempt")
    def agent():
        retrieve()
        return {"status": "completed"}

    @trace_operation("orchestrator")
    def completed():
        agent()
        return {"status": "completed"}

    @trace_operation("anamnesis_retrieval")
    def failed():
        raise ValueError("synthetic exception content must not enter telemetry")

    # Build the provider with its generator before requesting a tracer. The SDK
    # tracer captures the generator at construction; changing the provider later
    # does not reconfigure an existing tracer. Reuse the public helper's context,
    # decorators and shutdown behavior, with this fixture-only provider setup.
    telemetry = LocalTracing()
    identifiers = FixedIds()
    telemetry.exporter = InMemorySpanExporter()
    telemetry.provider = TracerProvider(
        resource=Resource({"service.name": "clinicalbridge-local-evaluation"}),
        id_generator=identifiers,
    )
    telemetry.provider.add_span_processor(SimpleSpanProcessor(telemetry.exporter))
    telemetry.tracer = telemetry.provider.get_tracer("clinicalbridge.evaluation")
    assert telemetry.tracer.id_generator is identifiers
    with telemetry.activate():
        completed()
        try:
            failed()
        except ValueError:
            pass
    spans = sorted(telemetry.exporter.get_finished_spans(), key=lambda s: s.start_time)
    start = spans[0].start_time
    recorded = [{
        "trace_id": format(s.context.trace_id, "032x"),
        "span_id": format(s.context.span_id, "016x"),
        "parent_span_id": format(s.parent.span_id, "016x") if s.parent else None,
        "name": s.name,
        "status": s.status.status_code.name,
        "start_offset_ns": s.start_time - start,
        "duration_ns": s.end_time - s.start_time,
        "attributes": dict(s.attributes),
        "events": [],
    } for s in spans]
    assert all(not s.events and s.status.description is None for s in spans)
    assert "synthetic exception content" not in "".join(s.to_json() for s in spans)
    telemetry.shutdown()
    assert [span["span_id"] for span in recorded] == [format(i, "016x") for i in range(1, 5)]
    return recorded


def record():
    from examples.tqen_mcp import (
        DEMO_PRINCIPAL, DOCUMENTS, INVOICES, InvoiceArgs, ReadOnlyBoundary,
        RetrievalArgs, tool_schemas,
    )

    recorded = capture_spans()

    boundary = ReadOnlyBoundary(DEMO_PRINCIPAL)
    outcomes = {}
    for invoice_id in ("invoice-a", "invoice-injection", "invoice-b", "invoice-other-branch", "invoice-missing"):
        try:
            outcomes[invoice_id] = boundary.invoice_review(InvoiceArgs(invoice_id=invoice_id))
        except ValueError as error:
            outcomes[invoice_id] = {"error": str(error)}
    results = {
        "format_version": 1,
        "recording": {
            "scope": "Offline recording of the published portable helper with synthetic function returns. Not the real clinical orchestrator, production traces, or a model run.",
            "command": "python docs/evidence/generate_evidence.py",
            "timing": "Observed local test nanoseconds only. Not a production latency benchmark. Fixed span IDs; timings vary when regenerated.",
            "identifiers": "Fixture-only fixed IDs configured before tracer creation. The error is a separate trace. Never use this generator in deployment.",
            "source": "examples/clinicalbridge_tracing.py",
        },
        "spans": recorded,
        "tqen": {
            "scope": asdict(DEMO_PRINCIPAL) | {"capabilities": sorted(DEMO_PRINCIPAL.capabilities)},
            "invoices": [asdict(i) for i in INVOICES if i.tenant_id == "tenant-a" and i.branch_id == "branch-1"],
            "documents": [asdict(d) for d in DOCUMENTS if d.tenant_id == "tenant-a" and d.branch_id == "branch-1"],
            "recorded_outcomes": outcomes,
            "recorded_retrieval": boundary.retrieve_supplier_context(RetrievalArgs(query="supplier")),
            "tools": [t.model_dump(exclude_none=True) for t in tool_schemas()],
        },
        "provenance": {
            "atg": {"commit": "133de892a49c9bb9b7cbe1437f8f0c7d40e14113", "commit_utc": "2026-11-01T13:21:16Z"},
            "mcp_and_tracing": {"commit": "c83a78e499cfba61631c48e511a43e846b573106", "commit_utc": "2026-11-01T23:46:23Z"},
            "upstream_clinicalbridge_instrumentation": {"commit": "470a671da74abca95e15a3853cd2318a740581de", "commit_utc": "2026-11-02T10:10:22Z"},
            "date_scope": "Original introducing commit timestamps verified in origin/main, not measured hosting timestamps.",
        },
    }
    transcript = []
    for suite in ("proof_tests/test_tqen_mcp.py", "proof_tests/test_clinicalbridge_tracing.py"):
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", suite]
        run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
        if run.returncode:
            raise SystemExit(run.stdout + run.stderr)
        transcript.append("$ python -m pytest -q -p no:cacheprovider " + suite + "\n" + run.stdout + run.stderr)
    (ROOT / "docs/evidence/explorer.json").write_text(json.dumps(results, indent=2) + "\n")
    (ROOT / "docs/evidence/recorded-tests.txt").write_text("\n".join(transcript))
    print("Recorded four synthetic-helper spans and public MCP outcomes; both proof suites passed.")


if __name__ == "__main__":
    record()
