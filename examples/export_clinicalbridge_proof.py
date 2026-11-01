"""Export reviewed local instrumentation against one known public prototype base.

Usage: python -m examples.export_clinicalbridge_proof /path/to/clinicalbridge
Only the named public-code changes are exported; no dataset or environment file.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BASE = "ceb134f0f2650b789c2bf6672229d3129b2f4b73"
MODIFIED = ["README.md", "agents/ehr_agent.py", "agents/anamnesis_agent.py", "orchestrator/orchestrator.py"]
ADDED = ["orchestrator/observability.py", "eval/test_observability.py", "requirements-observability.txt"]


def run(args, repo):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=60)


def main():
    repo = Path(sys.argv[1]).resolve()
    if run(["git", "rev-parse", "HEAD"], repo).stdout.strip() != BASE:
        raise SystemExit("Review the source base before exporting a different revision")
    remote = run(["git", "remote", "get-url", "origin"], repo).stdout.strip()
    if remote != "https://github.com/waelabokalam/clinicalbridge.git":
        raise SystemExit("Expected the independently verified public ClinicalBridge repository")
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "eval/test_observability.py"],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    diff = run(["git", "diff", "--binary", "--", *MODIFIED], repo)
    if diff.returncode:
        raise SystemExit("Cannot export reviewed diff")
    patch = diff.stdout
    for path in ADDED:
        new = run(["git", "diff", "--no-index", "--", "/dev/null", path], repo)
        if new.returncode != 1:
            raise SystemExit("Expected a new, reviewed proof file")
        patch += new.stdout
    transcript = "$ PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p no:cacheprovider eval/test_observability.py\n" + result.stdout + result.stderr
    (ROOT / "evidence/clinicalbridge-opentelemetry.patch").write_text(patch)
    (ROOT / "evidence/clinicalbridge-tracing-test-transcript.txt").write_text(transcript)
    source = (ROOT / "examples/clinicalbridge_tracing.py").read_text()
    actual = (repo / "orchestrator/observability.py").read_text()
    if source != actual:
        raise SystemExit("Exported helper must match the locally instrumented prototype")
    report = """# ClinicalBridge: payload-free OpenTelemetry evaluation traces

**Academic prototype | Locally tested instrumentation | Portable public proof**

This upgrade instruments the real ClinicalBridge `process_alert` orchestrator, its agent-call boundary and both EHR/anamnesis retrieval functions. The [reviewable patch](../evidence/clinicalbridge-opentelemetry.patch) applies to public base commit `""" + BASE + """`. The patch is prepared locally; publication of this case study does not imply that the original ClinicalBridge remote has been updated.

## Inspect the boundaries

```mermaid
flowchart TD
    A[orchestrator span] --> B[triage agent call]
    A --> C[EHR agent call]
    C --> D[EHR retrieval span: document count]
    A --> E[Anamnesis agent call]
    E --> F[Anamnesis retrieval span: document count]
    A --> G[synthesis agent call]
    H[Local in-memory exporter] --- A
```

- Tracing is opt-in and per-context. Disabled operation creates no exporter and does not change answers.
- The exporter stays in memory: no collector, credential, network exporter or global provider is configured.
- Closed operation names, bounded outcomes and document counts are exported. No prompts, patient identifiers, retrieved text, result payloads, exception messages or stack traces enter spans.
- Error paths record error status without exception content. Export failure leaves the workflow result unchanged.
- The underlying academic workflow's session logs are separate and unchanged; tracing does not make those logs redacted or establish clinical deployment readiness.

## Verification scope

Eight local tests exercise the real orchestrator with agent responses stubbed, and test the real EHR/anamnesis retrieval functions separately with model/vector adapters stubbed. They check parent-child relationships, hard patient retrieval filtering, disabled tracing, metadata-only exports, exception redaction, returned failures, offline export failure and closed operation names.

The portable [helper](../examples/clinicalbridge_tracing.py) and [public regression suite](../proof_tests/test_clinicalbridge_tracing.py) run with `python -m pytest -q -p no:cacheprovider proof_tests`. The original 5/5 gold scenarios and 15/15 designed failure checks remain historical project evaluation, including manual review; these new instrumentation tests are a separate count.

To reproduce the local integration proof, clone `https://github.com/waelabokalam/clinicalbridge.git`, check out the base above, apply the patch, install `requirements-observability.txt`, then run the command below. No model key or patient dataset is needed for those tests. The exporter follows the [official OpenTelemetry Python instrumentation API](https://opentelemetry.io/docs/languages/python/instrumentation/).

## Actual captured integration-test transcript

```text
""" + transcript.rstrip() + "\n```\n\n## Exported tracing helper\n\n```python\n" + source.rstrip() + "\n```\n"
    (ROOT / "case-studies/clinicalbridge-tracing.md").write_text(report)
    print(result.stdout.strip())
    print("Exported only the reviewed tracing code, patch and passing transcript.")


if __name__ == "__main__":
    main()
