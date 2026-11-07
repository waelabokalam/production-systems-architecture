"""Deterministic, in-memory OCR timeout replay. Only use synthetic extracts."""

import argparse
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from time import perf_counter_ns
from typing import Any, Callable, Iterable, Iterator

from ocr_telemetry import OCRTelemetry, TIMEOUT
from schema import LINE_FIELDS, load_dataset
from validator import assisted


DEMO_FIXTURE = "dev-01-ar-clean"
DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "invoices_v1.json"
MAX_ATTEMPTS = 2
Draft = dict[str, Any]
Stream = Iterable[dict[str, Any] | None]
StreamFactory = Callable[[Draft], Stream]


@dataclass(frozen=True)
class AttemptResult:
    fixture_id: str
    attempt_count: int
    retry_eligible: bool
    disposition: str
    error_code: str
    reconciliation_required: bool
    replayed: bool = False


def _simulate_worker(extract: Draft, *, timeout: bool) -> Iterator[dict[str, Any] | None]:
    for line in extract["lines"]:
        yield line
        if timeout:
            raise TimeoutError
    if timeout:
        raise TimeoutError
    yield None  # End marker; a bare EOF is not successful completion.


def _completed_extract(extract: Draft, stream: Stream) -> Draft:
    expected_count = len(extract["lines"])  # Synthetic framing contract.
    staged: list[dict[str, Any]] = []
    complete = False
    for line in stream:
        if complete:
            raise TimeoutError
        if line is None:
            complete = True
        elif (
            type(line) is not dict or line.keys() != set(LINE_FIELDS)
            or any(value is not None and type(value) is not str for value in line.values())
            or len(staged) >= expected_count
        ):
            raise TimeoutError
        else:
            staged.append(line.copy())
    if not complete or len(staged) != expected_count:
        raise TimeoutError
    return {**extract, "lines": staged}


class OCRWorkflow:
    """Serialize attempts per fixture in memory; never approve or post to a ledger."""

    def __init__(
        self, fixture_id: str, directory: list[dict[str, Any]], *,
        telemetry: OCRTelemetry | None = None, clock_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        self._fixture_id = fixture_id
        self._directory = directory
        self._telemetry = telemetry if telemetry is not None else OCRTelemetry(enable_otel=False)
        self._clock_ns = clock_ns
        self._lock = Lock()
        self._completed: dict[str, AttemptResult] = {}
        self._latest: AttemptResult | None = None
        self._draft: Draft | None = None
        self._reviewer_draft: Draft | None = None
        self._retry_suggestion: Draft | None = None

    @property
    def draft(self) -> Draft | None:
        with self._lock:
            return deepcopy(self._reviewer_draft if self._reviewer_draft is not None else self._draft)

    @property
    def retry_suggestion(self) -> Draft | None:
        with self._lock:
            return deepcopy(self._retry_suggestion)

    def record_reviewer_draft(self, draft: Draft) -> None:
        """Save a separate reviewer-owned snapshot while the timeout is in review."""
        with self._lock:
            if self._latest is None or self._latest.error_code != TIMEOUT:
                raise ValueError("a timed-out draft must be in review before editing")
            self._reviewer_draft = deepcopy(draft)

    def run_attempt(
        self, request_id: str, extract: Draft, *, simulate_timeout: bool = False,
        stream_factory: StreamFactory | None = None,
    ) -> AttemptResult:
        """Replay a request ID without work, or perform one allowed OCR attempt."""
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("an idempotency key is required")
        with self._lock:
            if request_id in self._completed:
                return replace(self._completed[request_id], replayed=True)
            if self._latest is not None and not self._latest.retry_eligible:
                raise ValueError("no OCR attempt is eligible")
            if stream_factory is not None and simulate_timeout:
                raise ValueError("choose an injected stream or a simulated timeout")

            attempt_count = len(self._completed) + 1
            with self._telemetry.attempt_span() as span:
                started = self._clock_ns()
                source = deepcopy(extract)
                try:
                    stream_input = deepcopy(source)
                    stream = (
                        stream_factory(stream_input) if stream_factory is not None
                        else _simulate_worker(stream_input, timeout=simulate_timeout)
                    )
                    candidate = _completed_extract(source, stream)
                except TimeoutError:
                    # Do not pass the exception, its message, or partial rows to the validator.
                    candidate = None
                timed_out = candidate is None
                needs_reconciliation = candidate is not None and self._reviewer_draft is not None
                issues = () if candidate is None else assisted(candidate, self._directory).error_codes
                sample = self._telemetry.record(
                    span, duration_ms=(self._clock_ns() - started) / 1_000_000,
                    timed_out=timed_out, validation_errors=issues,
                    reconciliation_required=needs_reconciliation,
                )
                result = AttemptResult(
                    fixture_id=self._fixture_id, attempt_count=attempt_count,
                    retry_eligible=timed_out and attempt_count < MAX_ATTEMPTS,
                    disposition=sample["disposition"], error_code=sample["error_code"],
                    reconciliation_required=needs_reconciliation,
                )
            if candidate is not None:
                if needs_reconciliation:
                    # A different extraction may reorder lines. Never replay edits by index.
                    self._retry_suggestion = candidate
                else:
                    self._draft = candidate
            self._completed[request_id] = self._latest = result
            return result


def _print_result(label: str, result: AttemptResult, sample: dict[str, Any] | None) -> None:
    detail = "" if sample is None else (
        f" status_code={sample['status_code']} duration_ms={sample['duration_ms']:g}"
    )
    print(
        f"{label}: attempt_count={result.attempt_count} {result.disposition} "
        f"error_code={result.error_code} retry_eligible={str(result.retry_eligible).lower()} "
        f"replayed={str(result.replayed).lower()} "
        f"reconciliation_required={str(result.reconciliation_required).lower()}{detail}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--no-otel", action="store_true", help="Use only local safe samples")
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.fixtures)
        invoice = next(row for row in dataset["invoices"] if row["fixture_id"] == DEMO_FIXTURE)
    except (OSError, ValueError, StopIteration):
        parser.error("cannot load the synthetic demo fixture")

    extract = invoice["frozen_ocr_extract"]
    directory = dataset["supplier_directory"]
    if assisted(extract, directory).disposition != "READY":
        parser.error("demo requires a clean synthetic fixture")
    print(f"Synthetic OCR timeout replay: {DEMO_FIXTURE} (fixed demo timings; no OCR provider)")
    with OCRTelemetry(enable_otel=not args.no_otel) as telemetry:
        print(f"Telemetry: {'OpenTelemetry in memory' if telemetry.sdk_enabled else 'local samples only'}")
        ticks = iter(n * 1_000_000 for n in (0, 750, 1000, 1120, 2000, 2750, 3000, 3120))
        workflow = OCRWorkflow(DEMO_FIXTURE, directory, telemetry=telemetry, clock_ns=ticks.__next__)
        failed = workflow.run_attempt("initial", extract, simulate_timeout=True)
        _print_result("timeout", failed, telemetry.samples[-1])
        no_partial = workflow.draft is None
        recovered = workflow.run_attempt("retry-1", extract)
        _print_result("recovery", recovered, telemetry.samples[-1])
        replay = workflow.run_attempt("retry-1", extract)
        _print_result("replayed retry (no execution)", replay, None)
        one_draft = workflow.draft == extract

        reviewed = OCRWorkflow(DEMO_FIXTURE, directory, telemetry=telemetry, clock_ns=ticks.__next__)
        reviewed.run_attempt("initial", extract, simulate_timeout=True)
        reviewer_draft = {**extract, "invoice_number": "SYNTHETIC-REVIEWER-EDIT"}
        reviewed.record_reviewer_draft(reviewer_draft)
        reconciled = reviewed.run_attempt("retry-1", extract)
        _print_result("recovery with reviewer edits", reconciled, telemetry.samples[-1])
        preserved = reviewed.draft == reviewer_draft and reviewed.retry_suggestion == extract
        print(
            f"Checks: partial_discarded={str(no_partial).lower()} "
            f"single_complete_draft={str(one_draft).lower()} "
            f"reviewer_edits_preserved={str(preserved).lower()} "
            f"observed_attempts={len(telemetry.samples)} ledger_writes=0"
        )
    return 0 if no_partial and one_draft and preserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
