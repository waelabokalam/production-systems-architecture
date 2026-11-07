# Runbook: OCR timeout and safe recovery

This lab replays synthetic frozen OCR, injects a timeout after a partial line stream, and retries with a complete extraction. It calls no OCR provider and makes no ledger writes. `READY` means the draft passed validation, not that it was approved.

From this directory:

```sh
python trace_failure_demo.py
python trace_failure_demo.py --no-otel
```

With the optional OpenTelemetry SDK, the demo keeps traces and metrics in memory. Without it, the same decisions run without SDK exports. Demo timing and sample rates are not production baselines.

## Monitor

| Signal | Read it over one time window |
| --- | --- |
| Latency | Track p50/p95 of `tqen.ocr.duration` (ms). Inspect `duration_ms` on `tqen.ocr.attempt` spans for slow attempts. |
| Timeout/error rate | Divide `tqen.ocr.attempts` with `error_code=ERR_OCR_TIMEOUT` by all executed attempts. Show counts alongside rates. Use `tqen.ocr.validation_errors` to see all distinct rule failures on complete extracts, not just the first code on the attempt. |
| Review spike | Divide attempts with `disposition=NEEDS_REVIEW` by all executed attempts. For a live queue, count unique invoice drafts by current disposition instead: a retry is another attempt, not another invoice. |

## Diagnose

1. **Worker timeout:** If `ERR_OCR_TIMEOUT` rises, check latency, worker availability, queue delay and the configured deadline. The incomplete stream never reached invoice validation. Keep the invoice in review while the worker is unhealthy.
2. **Validation or template drift:** If OCR completes but `ERR_LINE_TOTAL_MISMATCH` or `ERR_SUPPLIER_AMBIGUOUS` rises, check for a recent OCR/layout rollout or a stale supplier catalog before retrying. An ambiguous supplier alone does not establish template drift. Compare release timing and replay a synthetic reproduction. Inspect a source invoice only in the authorized review interface.
3. **Keep diagnostics payload-free:** Compare `duration_ms`, `status_code`, `error_code` and `disposition`. Never add raw OCR text, supplier names, amounts, or worker exception messages to spans, metrics or logs.

## Recover

1. Discard staged OCR lines on timeout. Check `fixture_id`, `attempt_count` and `retry_eligible` in workflow state. Once the worker is healthy, issue one new retry request for the same fixture; if delivery is uncertain, replay that request key instead of creating another. The demo allows two executed attempts per fixture; after the budget is spent, leave the invoice for manual review.
2. Validate only a complete retry. Replace an unedited draft as a whole; never append OCR lines. If a reviewer has edited the draft, keep it untouched and show the recovered extraction as a separate suggestion for explicit reconciliation. Do not merge by line position across attempts.
3. Replaying the same request key must not start another attempt or create another draft. The lab enforces this in one process, without durable storage. In production, persist request keys and results against a unique `(tenant_id, document_id)` draft, apply replacements in a transaction with a revision check, and reject stale worker results. Put ledger posting behind separate authorized approval and a database-enforced unique posting key; an OCR retry must never invoke posting.
