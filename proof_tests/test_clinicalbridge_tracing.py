"""Portable checks for the exported, payload-free tracing helper."""
from importlib.util import find_spec

import pytest

if find_spec("opentelemetry") is None or find_spec("opentelemetry.sdk") is None:
    pytest.importorskip("opentelemetry.sdk", exc_type=ModuleNotFoundError)

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from examples.clinicalbridge_tracing import LocalTracing, trace_operation


CANARY = "synthetic-patient@example.invalid PRIVATE-CLINICAL-TEXT"


def test_parent_child_relationships_and_payload_exclusion():
    @trace_operation("ehr_retrieval")
    def retrieve(query):
        return [query]
    @trace_operation("orchestrator")
    def run(alert):
        return {"status": "completed", "context": retrieve(alert)}
    telemetry = LocalTracing(enabled=True)
    with telemetry.activate():
        assert run(CANARY)["context"] == [CANARY]
    child, parent = telemetry.exporter.get_finished_spans()
    assert child.parent.span_id == parent.context.span_id
    assert child.context.trace_id == parent.context.trace_id
    assert child.attributes["clinicalbridge.document_count"] == 1
    assert CANARY not in child.to_json() + parent.to_json()
    telemetry.shutdown()


def test_disabled_is_transparent_and_does_not_create_a_provider():
    telemetry = LocalTracing()
    @trace_operation("orchestrator")
    def run(value):
        return value
    with telemetry.activate():
        assert run(CANARY) == CANARY
    assert telemetry.provider is None and telemetry.exporter is None


def test_errors_export_status_without_exception_content_or_stack():
    @trace_operation("anamnesis_retrieval")
    def fail():
        raise ValueError(CANARY)
    telemetry = LocalTracing(enabled=True)
    with telemetry.activate(), pytest.raises(ValueError):
        fail()
    span, = telemetry.exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description is None and not span.events
    assert CANARY not in span.to_json()
    telemetry.shutdown()


def test_returned_terminal_failure_is_an_error_without_payloads():
    @trace_operation("orchestrator")
    def fail():
        return {"status": "failed", "error": CANARY}
    telemetry = LocalTracing(enabled=True)
    with telemetry.activate():
        assert fail()["error"] == CANARY
    span, = telemetry.exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert CANARY not in span.to_json()
    telemetry.shutdown()


def test_exporter_failure_does_not_change_workflow_result():
    class Offline(SpanExporter):
        def export(self, spans):
            return SpanExportResult.FAILURE
    telemetry = LocalTracing(enabled=True, exporter=Offline())
    @trace_operation("orchestrator")
    def run():
        return {"status": "completed"}
    with telemetry.activate():
        assert run()["status"] == "completed"
    telemetry.shutdown()


def test_span_name_allowlist_and_context_reset():
    with pytest.raises(ValueError):
        trace_operation(CANARY)
    telemetry = LocalTracing(enabled=True)
    @trace_operation("orchestrator")
    def run():
        return {"status": "completed"}
    with telemetry.activate():
        run()
    run()
    assert len(telemetry.exporter.get_finished_spans()) == 1
    telemetry.shutdown()
