"""Optional proof-dependency checks for the explorer's actual OTel recording.

python -m pytest -q -p no:cacheprovider docs/tests/test_evidence_recorder.py
"""
import importlib.util
from pathlib import Path


RECORDER = Path(__file__).resolve().parents[1] / "evidence/generate_evidence.py"
SPEC = importlib.util.spec_from_file_location("explorer_evidence_recorder", RECORDER)
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)


def identities(spans):
    return [(s["trace_id"], s["span_id"], s["parent_span_id"], s["name"]) for s in spans]


def test_fixed_ids_are_captured_by_the_tracer_before_span_creation():
    spans = recorder.capture_spans()
    assert [s["span_id"] for s in spans] == [format(i, "016x") for i in range(1, 5)]
    assert [s["parent_span_id"] for s in spans] == [None, format(1, "016x"), format(2, "016x"), None]
    assert [s["trace_id"] for s in spans] == [format(1, "032x")] * 3 + [format(2, "032x")]
    assert spans[-1]["status"] == "ERROR"
    assert all(s["duration_ns"] > 0 for s in spans)


def test_fresh_recordings_keep_identifiers_and_preserve_actual_timings():
    first = recorder.capture_spans()
    second = recorder.capture_spans()
    assert identities(first) == identities(second)
    assert all(s["duration_ns"] > 0 and s["start_offset_ns"] >= 0 for s in first + second)
    for spans in (first, second):
        parent, agent, retrieval, failure = spans
        assert agent["start_offset_ns"] >= parent["start_offset_ns"]
        assert retrieval["start_offset_ns"] >= agent["start_offset_ns"]
        assert agent["start_offset_ns"] + agent["duration_ns"] <= parent["duration_ns"]
        assert failure["start_offset_ns"] >= parent["duration_ns"]
