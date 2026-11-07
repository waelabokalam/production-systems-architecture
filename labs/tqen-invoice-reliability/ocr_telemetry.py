"""Local, payload-free observability for the synthetic OCR demo."""

from contextlib import contextmanager
from math import isfinite
from typing import Any, Iterator


ATTEMPT_SPAN = "tqen.ocr.attempt"
ATTEMPT_COUNTER = "tqen.ocr.attempts"
DURATION_HISTOGRAM = "tqen.ocr.duration"
VALIDATION_COUNTER = "tqen.ocr.validation_errors"
TIMEOUT = "ERR_OCR_TIMEOUT"
RECONCILIATION = "ERR_REVIEWER_RECONCILIATION"
VALIDATION_CODES = frozenset({
    "ERR_CURRENCY_CONFLICT", "ERR_INVALID_DATE", "ERR_INVALID_NUMBER",
    "ERR_ITEM_AMBIGUOUS", "ERR_ITEM_UNKNOWN", "ERR_LINE_TOTAL_MISMATCH",
    "ERR_MISSING_FIELD", "ERR_SUBTOTAL_MISMATCH", "ERR_SUPPLIER_AMBIGUOUS",
    "ERR_SUPPLIER_UNKNOWN", "ERR_TOTAL_MISMATCH", "ERR_UNIT_CONFLICT",
})


def safe_validation_code(code: str) -> str:
    """Allowlist labels at the telemetry boundary; never pass through free text."""
    return code if code in VALIDATION_CODES else "ERR_VALIDATION"


class OCRTelemetry:
    """Use isolated SDK providers if installed; otherwise retain safe local samples."""

    def __init__(self, *, enable_otel: bool = True) -> None:
        self._samples: list[dict[str, Any]] = []
        self._tracer = None
        if not enable_otel:
            return
        try:
            from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter, MeterProvider
            from opentelemetry.sdk.metrics.export import InMemoryMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
            from opentelemetry.sdk.trace.sampling import ALWAYS_ON
            from opentelemetry.context import Context
            from opentelemetry.metrics import NoOpMeterProvider
            from opentelemetry.trace import Status, StatusCode
        except ModuleNotFoundError as exc:
            if exc.name in {"opentelemetry", "opentelemetry.sdk"}:
                return
            raise

        # Local providers and in-memory readers follow the SDK instrumentation APIs:
        # https://opentelemetry.io/docs/languages/python/instrumentation/
        # Explicit Resource avoids discovering arbitrary environment attributes.
        scope = "tqen-invoice-reliability-lab"
        resource = Resource({"service.name": scope})
        noop_metrics = NoOpMeterProvider()
        self._context = Context()
        self._status = Status
        self._status_code = StatusCode
        self._span_exporter = InMemorySpanExporter()
        self._trace_provider = TracerProvider(
            sampler=ALWAYS_ON, resource=resource, shutdown_on_exit=False,
            meter_provider=noop_metrics,
        )
        self._trace_provider.add_span_processor(SimpleSpanProcessor(
            self._span_exporter, meter_provider=noop_metrics,
        ))
        self._tracer = self._trace_provider.get_tracer(scope)
        self._metric_reader = InMemoryMetricReader()
        self._meter_provider = MeterProvider(
            metric_readers=[self._metric_reader], resource=resource,
            exemplar_filter=AlwaysOffExemplarFilter(), shutdown_on_exit=False,
        )
        meter = self._meter_provider.get_meter(scope)
        self._attempts = meter.create_counter(ATTEMPT_COUNTER, unit="1")
        self._duration = meter.create_histogram(DURATION_HISTOGRAM, unit="ms")
        self._validation_errors = meter.create_counter(VALIDATION_COUNTER, unit="1")

    @property
    def sdk_enabled(self) -> bool:
        return self._tracer is not None

    @property
    def samples(self) -> tuple[dict[str, Any], ...]:
        return tuple(sample.copy() for sample in self._samples)

    def spans(self) -> tuple[Any, ...]:
        return self._span_exporter.get_finished_spans() if self.sdk_enabled else ()

    def metrics_data(self) -> Any:
        return self._metric_reader.get_metrics_data() if self.sdk_enabled else None

    @contextmanager
    def attempt_span(self) -> Iterator[Any]:
        if not self.sdk_enabled:
            yield None
            return
        # No ambient parent, automatic exception event/description, or current span.
        with self._tracer.start_span(
            ATTEMPT_SPAN, context=self._context, record_exception=False,
            set_status_on_exception=False,
        ) as span:
            yield span

    def record(
        self,
        span: Any,
        *,
        duration_ms: float,
        timed_out: bool,
        validation_errors: tuple[str, ...],
        reconciliation_required: bool,
    ) -> dict[str, Any]:
        codes = tuple(dict.fromkeys(map(safe_validation_code, validation_errors)))
        error_code = (
            TIMEOUT if timed_out else codes[0] if codes
            else RECONCILIATION if reconciliation_required else "NONE"
        )
        labels = {
            "status_code": "ERROR" if timed_out else "OK",
            "error_code": error_code,
            "disposition": "READY" if error_code == "NONE" else "NEEDS_REVIEW",
        }
        if not isfinite(duration_ms) or duration_ms < 0:
            raise ValueError("attempt duration must be finite and nonnegative")
        sample = {**labels, "duration_ms": duration_ms}
        self._samples.append(sample)
        if self.sdk_enabled:
            span.set_attributes(sample)
            span.set_status(self._status(self._status_code[labels["status_code"]]))
            self._attempts.add(1, labels, context=self._context)
            self._duration.record(duration_ms, labels, context=self._context)
            for code in codes:
                self._validation_errors.add(1, {"error_code": code}, context=self._context)
        return sample.copy()

    def __enter__(self) -> "OCRTelemetry":
        return self

    def __exit__(self, *_: Any) -> None:
        if self.sdk_enabled:
            self._trace_provider.shutdown()
            self._meter_provider.shutdown()
