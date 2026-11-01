"""Opt-in, local OpenTelemetry without clinical text or process-global exporters.

SDK pattern: https://opentelemetry.io/docs/languages/python/instrumentation/
Only closed operation names, outcomes and document counts enter spans. Arguments,
results, patient identifiers, prompts and exception text never enter telemetry.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


_tracer = ContextVar("clinicalbridge_tracer", default=None)
OPERATIONS = frozenset({"orchestrator", "agent_attempt", "ehr_retrieval", "anamnesis_retrieval"})
OUTCOMES = frozenset({"completed", "failed", "escalated_critical"})


def trace_operation(operation):
    if operation not in OPERATIONS:
        raise ValueError("Unregistered trace operation")

    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            tracer = _tracer.get()
            if tracer is None:
                return fn(*args, **kwargs)
            from opentelemetry.trace import Status, StatusCode

            # Explicitly disable automatic exception/stack capture: exception
            # messages can contain clinical text even when arguments are omitted.
            with tracer.start_as_current_span(
                "clinicalbridge." + operation,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    result = fn(*args, **kwargs)
                except Exception:
                    span.set_status(Status(StatusCode.ERROR))
                    raise
                outcome = result.get("status") if isinstance(result, dict) else None
                if outcome in OUTCOMES:
                    span.set_attribute("clinicalbridge.outcome", outcome)
                if operation.endswith("retrieval") and isinstance(result, list):
                    span.set_attribute("clinicalbridge.document_count", len(result))
                span.set_status(Status(StatusCode.ERROR if outcome == "failed" else StatusCode.OK))
                return result
        return wrapped
    return decorate


class LocalTracing:
    """No endpoint, credential, network exporter or global provider is configured."""
    def __init__(self, *, enabled=False, exporter=None):
        self.provider = self.tracer = self.exporter = None
        if enabled:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
            self.exporter = exporter if exporter is not None else InMemorySpanExporter()
            self.provider = TracerProvider(resource=Resource({"service.name": "clinicalbridge-local-evaluation"}))
            self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
            self.tracer = self.provider.get_tracer("clinicalbridge.evaluation")

    @contextmanager
    def activate(self):
        token = _tracer.set(self.tracer)
        try:
            yield self
        finally:
            _tracer.reset(token)

    def shutdown(self):
        if self.provider is not None:
            self.provider.shutdown()
