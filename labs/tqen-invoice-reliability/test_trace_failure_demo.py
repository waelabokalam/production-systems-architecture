"""Regression checks for timeout recovery and payload-free telemetry."""

from copy import deepcopy
from importlib.util import find_spec
import json
import logging
from pathlib import Path
import subprocess
import sys

import pytest

from schema import load_dataset
import trace_failure_demo as demo


LAB = Path(__file__).resolve().parent
FIXTURE_ID = "dev-01-ar-clean"
RAW_CANARIES = ("نص فاتورة اصطناعي __RAW_OCR_CANARY__", "second-line-private-ocr-token")
SUPPLIER_CANARY = "Synthetic Test Supplier __SUPPLIER_CANARY__"
AMOUNT_CANARY = "294871631.2500137"
CANARIES = (*RAW_CANARIES, SUPPLIER_CANARY, AMOUNT_CANARY)


@pytest.fixture
def clean():
    data = load_dataset(LAB / "fixtures" / "invoices_v1.json")
    fixture = next(row for row in data["invoices"] if row["fixture_id"] == FIXTURE_ID)
    return fixture["frozen_ocr_extract"], data["supplier_directory"]


def _unexpected_worker(_):
    pytest.fail("a duplicate or terminal attempt must not call the OCR worker")


def test_timeout_discards_partial_stream_and_retry_replaces_once(clean, monkeypatch):
    extract, directory = clean
    assert len(extract["lines"]) > 1
    original = deepcopy(extract)
    with demo.OCRTelemetry(enable_otel=False) as telemetry:
        workflow = demo.OCRWorkflow(FIXTURE_ID, directory, telemetry=telemetry)
        with monkeypatch.context() as patch:
            patch.setattr(demo, "assisted", lambda *_: pytest.fail("partial data reached the validator"))
            first = workflow.run_attempt("first", extract, simulate_timeout=True)

        assert first.fixture_id == FIXTURE_ID
        assert (first.attempt_count, first.retry_eligible) == (1, True)
        assert (first.disposition, first.error_code) == ("NEEDS_REVIEW", "ERR_OCR_TIMEOUT")
        assert not first.replayed
        assert workflow.draft is None and workflow.retry_suggestion is None

        repeated_failure = workflow.run_attempt("first", extract, stream_factory=_unexpected_worker)
        assert repeated_failure.replayed and repeated_failure.attempt_count == 1
        assert repeated_failure.disposition == "NEEDS_REVIEW"
        assert len(telemetry.samples) == 1

        recovered = workflow.run_attempt("retry", extract)
        assert (recovered.attempt_count, recovered.retry_eligible) == (2, False)
        assert (recovered.disposition, recovered.error_code) == ("READY", "NONE")
        assert not recovered.reconciliation_required and not recovered.replayed
        assert workflow.draft == original
        assert workflow.retry_suggestion is None

        repeated_retry = workflow.run_attempt("retry", extract, stream_factory=_unexpected_worker)
        assert repeated_retry.replayed and repeated_retry.attempt_count == 2
        assert repeated_retry.disposition == "READY"
        with pytest.raises(ValueError):
            workflow.run_attempt("terminal", extract, stream_factory=_unexpected_worker)
        assert workflow.draft == original and extract == original
        assert len(telemetry.samples) == 2


@pytest.mark.parametrize("truncated", [True, False], ids=["missing-end-marker", "malformed-line"])
def test_bad_stream_cannot_be_ready_after_retry(clean, truncated):
    extract, directory = clean
    with demo.OCRTelemetry(enable_otel=False) as telemetry:
        workflow = demo.OCRWorkflow(FIXTURE_ID, directory, telemetry=telemetry)
        workflow.run_attempt("first", extract, simulate_timeout=True)

        def bad_stream(doc):
            yield doc["lines"][0]
            if not truncated:
                yield {"unexpected": "incomplete worker chunk"}
                yield None

        retry = workflow.run_attempt("retry", extract, stream_factory=bad_stream)
        assert (retry.disposition, retry.error_code) == ("NEEDS_REVIEW", "ERR_OCR_TIMEOUT")
        assert (retry.attempt_count, retry.retry_eligible) == (2, False)
        assert workflow.draft is None and workflow.retry_suggestion is None
        assert len(telemetry.samples) == 2


def test_reviewed_draft_survives_retry_without_positional_merge(clean):
    extract, directory = clean
    edited = deepcopy(extract)
    edited["invoice_number"] += "-REVIEWED"
    edited["lines"][0]["quantity"] = "17"
    recovered = deepcopy(extract)
    recovered["lines"].reverse()

    workflow = demo.OCRWorkflow(FIXTURE_ID, directory)
    workflow.run_attempt("first", extract, simulate_timeout=True)
    workflow.record_reviewer_draft(edited)
    retry = workflow.run_attempt("retry", recovered)
    assert retry.disposition == "NEEDS_REVIEW" and retry.reconciliation_required
    assert retry.error_code == "ERR_REVIEWER_RECONCILIATION"
    assert (retry.attempt_count, retry.retry_eligible) == (2, False)
    assert workflow.draft == edited
    assert workflow.retry_suggestion == recovered
    assert workflow.run_attempt("retry", recovered, stream_factory=_unexpected_worker).replayed
    assert workflow.draft == edited and workflow.retry_suggestion == recovered


def test_complete_retry_still_requires_deterministic_validation(clean):
    extract, directory = clean
    invalid = deepcopy(extract)
    invalid["lines"][0]["quantity"] = "999999"
    workflow = demo.OCRWorkflow(FIXTURE_ID, directory)
    workflow.run_attempt("first", extract, simulate_timeout=True)
    result = workflow.run_attempt("retry", invalid)
    assert (result.disposition, result.error_code) == ("NEEDS_REVIEW", "ERR_LINE_TOTAL_MISMATCH")
    assert (result.attempt_count, result.retry_eligible) == (2, False)


def _private_example():
    line = {
        "item_name": "brown rice", "quantity": "1", "unit": "kg",
        "unit_price": AMOUNT_CANARY, "line_total": AMOUNT_CANARY, "currency": "USD",
    }
    extract = {
        "raw_text": "\n".join(RAW_CANARIES), "invoice_number": "SYN-PRIVATE",
        "invoice_date": "2026-02-01", "supplier_name": SUPPLIER_CANARY, "currency": "USD",
        "stated_total": AMOUNT_CANARY, "subtotal": AMOUNT_CANARY, "tax_amount": "0", "lines": [line],
    }
    directory = [{
        "canonical_name": SUPPLIER_CANARY, "currency": "USD",
        "items": [{"name": "brown rice", "unit": "kg"}],
    }]
    return extract, directory


def _assert_no_payload(serialized):
    for canary in CANARIES:
        assert canary not in serialized
        assert json.dumps(canary)[1:-1] not in serialized


def test_no_site_packages_cli_recovers_without_printing_invoice(tmp_path):
    extract, directory = _private_example()
    fixtures = tmp_path / "synthetic-fixture.json"
    fixtures.write_text(json.dumps({
        "schema_version": 1, "source": "synthetic_frozen_ocr", "supplier_directory": directory,
        "invoices": [{
            "fixture_id": FIXTURE_ID, "template_id": "private-demo-template", "supplier_family": "demo",
            "split": "dev", "language": "mixed", "failure_mode": "clean", "frozen_ocr_extract": extract,
            "ground_truth": {
                "supplier_canonical": SUPPLIER_CANARY, "currency": "USD", "stated_total": AMOUNT_CANARY,
                "calculated_line_sum": AMOUNT_CANARY, "expected_disposition": "READY",
            },
        }],
    }), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-B", "-E", "-S", "-X", "utf8", str(LAB / "trace_failure_demo.py"),
         "--fixtures", str(fixtures)],
        cwd=tmp_path, env={}, capture_output=True, text=True, encoding="utf-8", timeout=15,
        check=True,
    )
    assert "Telemetry: local samples only" in result.stdout
    assert "ERR_OCR_TIMEOUT" in result.stdout and "NEEDS_REVIEW" in result.stdout
    assert any("READY" in line and "NEEDS_REVIEW" not in line for line in result.stdout.splitlines())
    assert "ledger_writes=0" in result.stdout
    assert not result.stderr
    _assert_no_payload(result.stdout + result.stderr)


def test_exported_spans_metrics_and_logs_never_carry_invoice_payload(caplog, capsys, monkeypatch):
    if find_spec("opentelemetry") is None or find_spec("opentelemetry.sdk") is None:
        pytest.importorskip("opentelemetry.sdk", exc_type=ModuleNotFoundError)
    from opentelemetry.trace import NonRecordingSpan, SpanContext, StatusCode, use_span

    extract, directory = _private_example()
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", f"invoice.amount={AMOUNT_CANARY}")

    def timeout_with_payload(doc):
        yield doc["lines"][0]
        raise TimeoutError("\n".join(CANARIES))

    ambient = NonRecordingSpan(SpanContext(trace_id=11, span_id=12, is_remote=False))
    with demo.OCRTelemetry() as telemetry, use_span(ambient):
        assert telemetry.sdk_enabled
        workflow = demo.OCRWorkflow(FIXTURE_ID, directory, telemetry=telemetry)
        timed_out = workflow.run_attempt("first", extract, stream_factory=timeout_with_payload)
        assert timed_out.disposition == "NEEDS_REVIEW"

        invalid = deepcopy(extract)
        invalid["supplier_name"] += " LLC"  # Validator sees a near match and a candidate name.
        invalid["lines"][0]["quantity"] = "2"
        review = workflow.run_attempt("retry", invalid)
        assert review.disposition == "NEEDS_REVIEW" and not review.retry_eligible
        assert workflow.run_attempt("retry", invalid, stream_factory=_unexpected_worker).replayed

        spans = telemetry.spans()
        assert len(spans) == 2
        for span, status, code in zip(
            spans, (StatusCode.ERROR, StatusCode.OK), ("ERR_OCR_TIMEOUT", "ERR_SUPPLIER_AMBIGUOUS"),
        ):
            assert span.name == "tqen.ocr.attempt" and span.status.status_code is status
            assert span.parent is None
            assert not span.events and span.status.description is None
            assert dict(span.resource.attributes) == {"service.name": "tqen-invoice-reliability-lab"}
            duration = span.attributes["duration_ms"]
            assert type(duration) in (int, float) and duration >= 0
            assert dict(span.attributes) == {
                "duration_ms": duration, "status_code": status.name,
                "error_code": code, "disposition": "NEEDS_REVIEW",
            }
            _assert_no_payload(span.to_json())

        metrics = telemetry.metrics_data()
        assert len(metrics.resource_metrics) == 1
        assert dict(metrics.resource_metrics[0].resource.attributes) == {
            "service.name": "tqen-invoice-reliability-lab",
        }
        points = {
            metric.name: metric.data.data_points
            for resource in metrics.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }
        assert points.keys() == {"tqen.ocr.attempts", "tqen.ocr.duration", "tqen.ocr.validation_errors"}
        for name, count_field in (("tqen.ocr.attempts", "value"), ("tqen.ocr.duration", "count")):
            assert len(points[name]) == 2
            assert {tuple(sorted(point.attributes.items())) for point in points[name]} == {
                (("disposition", "NEEDS_REVIEW"), ("error_code", "ERR_OCR_TIMEOUT"), ("status_code", "ERROR")),
                (("disposition", "NEEDS_REVIEW"), ("error_code", "ERR_SUPPLIER_AMBIGUOUS"), ("status_code", "OK")),
            }
            assert all(getattr(point, count_field) == 1 for point in points[name])
        durations = {span.attributes["error_code"]: span.attributes["duration_ms"] for span in spans}
        for point in points["tqen.ocr.duration"]:
            assert point.sum == pytest.approx(durations[point.attributes["error_code"]])
        errors = points["tqen.ocr.validation_errors"]
        assert {tuple(point.attributes.items()) for point in errors} == {
            (("error_code", "ERR_LINE_TOTAL_MISMATCH"),), (("error_code", "ERR_SUPPLIER_AMBIGUOUS"),),
        }
        assert all(point.value == 1 for point in errors)
        _assert_no_payload(metrics.to_json())

    stdio = capsys.readouterr()
    _assert_no_payload(caplog.text + stdio.out + stdio.err)
