"""Provider-free regression tests for the synthetic replay and review boundary."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from unicodedata import normalize

import pytest

from run_eval import evaluate
from schema import load_dataset, validate_dataset
from validator import assisted, baseline, parse_decimal, parse_invoice_date, replay_review


LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
FIXTURES = LAB / "fixtures" / "invoices_v1.json"
AGREEMENT_FIELDS = ("supplier", "currency", "stated_total", "calculated_line_sum")
EXPECTED_FROZEN_ERRORS = {
    "dev-03-digit-drop": ("ERR_LINE_TOTAL_MISMATCH",),
    "dev-04-tax-total": ("ERR_TOTAL_MISMATCH",),
    "dev-05-currency-unit": ("ERR_CURRENCY_CONFLICT",),
    "dev-08-five-line-drop": ("ERR_LINE_TOTAL_MISMATCH",),
    "dev-09-ar-digit-substitution": ("ERR_LINE_TOTAL_MISMATCH",),
    "dev-10-ar-supplier-alias": ("ERR_SUPPLIER_AMBIGUOUS",),
    "dev-12-kg-gram": ("ERR_UNIT_CONFLICT",),
    "dev-13-missing-date": ("ERR_MISSING_FIELD",),
    "dev-15-zero-unit-price": ("ERR_INVALID_NUMBER",),
    "dev-17-catalog-currency": ("ERR_CURRENCY_CONFLICT",),
    "dev-19-carton-piece": ("ERR_UNIT_CONFLICT",),
    "dev-20-cent-tax": ("ERR_TOTAL_MISMATCH",),
    "holdout-03-supplier-alias": ("ERR_SUPPLIER_AMBIGUOUS",),
    "holdout-04-subtotal": ("ERR_SUBTOTAL_MISMATCH",),
    "holdout-05-missing-total": ("ERR_MISSING_FIELD",),
    "holdout-08-five-line-cent-tax": ("ERR_TOTAL_MISMATCH",),
    "holdout-09-ar-digit-substitution": ("ERR_LINE_TOTAL_MISMATCH",),
    "holdout-10-ar-supplier-alias": ("ERR_SUPPLIER_AMBIGUOUS",),
    "holdout-12-line-currency": ("ERR_CURRENCY_CONFLICT",),
    "holdout-13-missing-date": ("ERR_MISSING_FIELD",),
    "holdout-15-zero-unit-price": ("ERR_INVALID_NUMBER",),
    "holdout-16-carton-piece": ("ERR_UNIT_CONFLICT",),
    "holdout-18-missing-header-currency": ("ERR_MISSING_FIELD",),
    "holdout-19-exact-decimal": (),
    "holdout-20-balanced-unit": ("ERR_UNIT_CONFLICT",),
}


@pytest.fixture
def dataset():
    return load_dataset(FIXTURES)


@pytest.fixture(scope="module")
def frozen_rows():
    return {row["fixture_id"]: row for row in evaluate(load_dataset(FIXTURES))["invoices"]}


@pytest.fixture
def example():
    """A clean, independent input for one-rule-at-a-time perturbations."""
    extract = {
        "raw_text": "Synthetic invoice SYN-TEST",
        "invoice_number": "SYN-TEST",
        "invoice_date": "٢٠٢٤-٠٢-٢٩",
        "supplier_name": "  north orchard foods ",
        "currency": "SYP",
        "stated_total": "١١٫٠٠",
        "subtotal": "10.00",
        "tax_amount": "1.00",
        "lines": [
            {
                "item_name": "brown rice",
                "quantity": "2",
                "unit": "kg",
                "unit_price": "5.00",
                "line_total": "10.00",
                "currency": "SYP",
            }
        ],
    }
    directory = [
        {
            "canonical_name": "North Orchard Foods",
            "currency": "SYP",
            "items": [{"name": "Brown Rice", "unit": "kg"}],
        }
    ]
    return extract, directory


def test_frozen_design_and_ground_truth_dispositions(dataset):
    invoices = dataset["invoices"]
    assert len(invoices) == 40
    assert {invoice["failure_mode"] for invoice in invoices} == {
        "clean",
        "bad_scan_digit_drop",
        "similar_supplier_alias",
        "math_total_mismatch",
        "currency_unit_mismatch",
        "missing_critical_field",
        "zero_unit_price",
    }
    assert {
        invoice["fixture_id"]
        for invoice in invoices
        if invoice["ground_truth"]["expected_disposition"] == "NEEDS_REVIEW"
    } == {
        fixture_id for fixture_id, codes in EXPECTED_FROZEN_ERRORS.items() if codes
    }
    report = evaluate(dataset)
    rows = {row["fixture_id"]: row for row in report["invoices"]}
    assert len(rows) == len(invoices)
    assert set(rows) == {invoice["fixture_id"] for invoice in invoices}

    separation = {}
    for split in ("dev", "holdout"):
        subset = [invoice for invoice in invoices if invoice["split"] == split]
        assert len(subset) == 20
        assert sum(invoice["failure_mode"] == "clean" for invoice in subset) == 8
        assert {"ar", "en"} <= {invoice["language"] for invoice in subset}
        separation[split] = {
            "template": {invoice["template_id"] for invoice in subset},
            "family": {invoice["supplier_family"] for invoice in subset},
            "canonical_supplier": {
                " ".join(normalize("NFKC", invoice["ground_truth"]["supplier_canonical"]).casefold().split())
                for invoice in subset
            },
        }
        for invoice in subset:
            expected = invoice["ground_truth"]["expected_disposition"]
            mode = invoice["failure_mode"]
            assert expected == ("READY" if mode == "clean" else "NEEDS_REVIEW")
            row = rows[invoice["fixture_id"]]
            assert row["baseline"].disposition == "READY"
            assert row["assisted"].disposition == expected, row["fixture_id"]

    for field, values in separation["dev"].items():
        assert values.isdisjoint(separation["holdout"][field]), field
    # Raw agreement counts were calculated independently from the frozen extracts and labels.
    for split, n, clean_count, expected_matches, missing_dates in (
        ("dev", 20, 8, (19, 19, 18, 17), 1),
        ("holdout", 20, 8, (18, 19, 18, 19), 1),
        ("overall", 40, 16, (37, 38, 36, 36), 2),
    ):
        summary = report["splits"][split]
        assert summary["n"] == n
        assert summary["baseline"]["correct_ready"] == clean_count
        assert summary["baseline"]["wrong_ready"] == n - clean_count
        assert summary["baseline"]["review_count"] == 0
        assert summary["baseline"]["review_rate"] == 0
        assert summary["assisted"]["correct_ready"] == clean_count
        assert summary["assisted"]["wrong_ready"] == 0
        assert summary["assisted"]["review_count"] == n - clean_count
        assert summary["assisted"]["review_rate"] == pytest.approx((n - clean_count) / n)
        assert set(summary["agreement"]) == set(AGREEMENT_FIELDS)
        for field, matches in zip(AGREEMENT_FIELDS, expected_matches, strict=True):
            assert summary["agreement"][field]["n"] == n
            assert summary["agreement"][field]["matches"] == matches
        assert summary["date_coverage"] == {"valid": n - missing_dates, "invalid": 0, "missing": missing_dates}


@pytest.mark.parametrize("fixture_id", EXPECTED_FROZEN_ERRORS)
def test_frozen_scenarios_route_for_the_expected_reasons(frozen_rows, fixture_id):
    expected_codes = EXPECTED_FROZEN_ERRORS[fixture_id]
    row = frozen_rows[fixture_id]
    result = row["assisted"]
    assert result.error_codes == expected_codes
    assert result.disposition == ("NEEDS_REVIEW" if expected_codes else "READY")
    expected_mismatches = {
        "dev-03-digit-drop": {"calculated_line_sum"},
        "dev-04-tax-total": {"stated_total"},
        "holdout-03-supplier-alias": {"supplier"},
        "holdout-04-subtotal": set(),
        "holdout-05-missing-total": {"stated_total"},
        "holdout-19-exact-decimal": set(),
        "holdout-20-balanced-unit": set(),
    }
    if fixture_id in expected_mismatches:
        assert row["agreement"] == {
            field: field not in expected_mismatches[fixture_id] for field in AGREEMENT_FIELDS
        }
    if fixture_id in {"dev-10-ar-supplier-alias", "holdout-10-ar-supplier-alias"}:
        assert len(result.supplier_candidates) >= 2


def test_evaluation_counts_invalid_date_separately_from_missing_date(dataset):
    invoice = next(invoice for invoice in dataset["invoices"] if invoice["failure_mode"] == "clean")
    extract = invoice["frozen_ocr_extract"]
    split = invoice["split"]
    before = evaluate(dataset)["splits"][split]["date_coverage"]
    for value, state in (("2026-02-29", "invalid"), (None, "missing")):
        extract["invoice_date"] = value
        report = evaluate(dataset)
        after = report["splits"][split]["date_coverage"]
        assert after == {**before, "valid": before["valid"] - 1, state: before[state] + 1}
        row = next(row for row in report["invoices"] if row["fixture_id"] == invoice["fixture_id"])
        assert row["date_status"] == state


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", "0"), ("\t١٬٢٣٤٫٥٠\u00a0", "1234.50"), (" ۱۲٫۵۰ ", "12.50")],
)
def test_decimal_normalizes_arabic_digits_grouping_and_outer_whitespace(raw, expected):
    assert parse_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["1e3", "1,000", "١٢٬٣٤", "12 34", "1.2.3", "NaN", "SYP 12"])
def test_decimal_rejects_ambiguous_or_malformed_amounts(raw):
    with pytest.raises(ValueError):
        parse_decimal(raw)


@pytest.mark.parametrize("raw", ["2024-02-29", "٢٠٢٤-٠٢-٢٩", "۲۰۲۴-۰۲-۲۹"])
def test_iso_date_normalizes_localized_digits(raw):
    assert parse_invoice_date(raw).isoformat() == "2024-02-29"


def test_normalized_exact_matches_can_be_ready(example):
    extract, directory = example
    extract.update(tax_amount="٠", stated_total="١٠٫٠٠")
    result = assisted(extract, directory)
    assert result.disposition == "READY"
    assert not result.error_codes


def test_fuzzy_supplier_is_a_candidate_but_never_an_acceptance(example):
    extract, directory = example
    extract["supplier_name"] = "North Orchrd Foods"
    result = assisted(extract, directory)
    assert result.disposition == "NEEDS_REVIEW"
    assert result.error_codes == ("ERR_SUPPLIER_AMBIGUOUS",)
    assert result.supplier_candidates == ("North Orchard Foods",)


@pytest.mark.parametrize(
    ("header", "line", "code", "path"),
    [
        ({"invoice_date": None}, {}, "ERR_MISSING_FIELD", "invoice_date"),
        ({"invoice_date": "2026-02-29"}, {}, "ERR_INVALID_DATE", "invoice_date"),
        ({"invoice_date": "2026-2-08"}, {}, "ERR_INVALID_DATE", "invoice_date"),
        ({"invoice_date": "08/09/2026"}, {}, "ERR_INVALID_DATE", "invoice_date"),
        ({"stated_total": None}, {}, "ERR_MISSING_FIELD", "stated_total"),
        ({"stated_total": "11,00"}, {}, "ERR_INVALID_NUMBER", "stated_total"),
        ({"tax_amount": "not-a-number"}, {}, "ERR_INVALID_NUMBER", "tax_amount"),
        ({"currency": "USD"}, {}, "ERR_CURRENCY_CONFLICT", "currency"),
        ({}, {"currency": "USD"}, "ERR_CURRENCY_CONFLICT", "lines[0].currency"),
        ({}, {"unit": "piece"}, "ERR_UNIT_CONFLICT", "lines[0].unit"),
        ({}, {"item_name": "Brown Rce"}, "ERR_ITEM_UNKNOWN", "lines[0].item_name"),
        ({}, {"quantity": "3"}, "ERR_LINE_TOTAL_MISMATCH", "lines[0].line_total"),
        (
            {"subtotal": "0", "stated_total": "1"},
            {"unit_price": "0", "line_total": "0"},
            "ERR_INVALID_NUMBER",
            "lines[0].unit_price",
        ),
        ({"subtotal": "11.00", "stated_total": "12.00"}, {}, "ERR_SUBTOTAL_MISMATCH", "subtotal"),
        ({"tax_amount": "2.00"}, {}, "ERR_TOTAL_MISMATCH", "stated_total"),
    ],
)
def test_invalid_evidence_requires_review_with_specific_issue(example, header, line, code, path):
    extract, directory = example
    extract.update(header)
    extract["lines"][0].update(line)
    assert baseline(extract).disposition == "READY"
    result = assisted(extract, directory)
    assert result.disposition == "NEEDS_REVIEW"
    assert result.error_codes == (code,)
    assert path in {issue.path for issue in result.issues}


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("template_id", "(?i)template"),
        ("supplier_family", "(?i)family"),
        ("supplier_canonical", "(?i)supplier"),
    ],
)
def test_schema_rejects_split_leakage(dataset, field, message):
    dev = next(invoice for invoice in dataset["invoices"] if invoice["split"] == "dev")
    holdout = next(invoice for invoice in dataset["invoices"] if invoice["split"] == "holdout")
    if field == "supplier_canonical":
        holdout["ground_truth"][field] = f"  {dev['ground_truth'][field]}   "
    else:
        holdout[field] = dev[field]
    with pytest.raises(ValueError, match=message):
        validate_dataset(dataset)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), 2),
        (("source",), "live_ocr"),
        (("invoices", 0, "split"), "test"),
        (("invoices", 0, "supplier_family"), "Invalid Family"),
        (("invoices", 0, "frozen_ocr_extract", "invoice_date"), 20260413),
        (("invoices", 0, "frozen_ocr_extract", "stated_total"), 11),
        (("invoices", 0, "frozen_ocr_extract", "expected_disposition"), "READY"),
        (("invoices", 0, "frozen_ocr_extract", "lines", 0, "approved"), True),
        (("invoices", 0, "ground_truth", "expected_disposition"), "APPROVED"),
    ],
)
def test_schema_rejects_invalid_and_extra_fields(dataset, path, replacement):
    target = dataset
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(ValueError):
        validate_dataset(dataset)


def test_schema_requires_date_key_even_when_its_value_can_be_null(dataset):
    extract = dataset["invoices"][0]["frozen_ocr_extract"]
    extract["invoice_date"] = None
    validate_dataset(dataset)
    del extract["invoice_date"]
    with pytest.raises(ValueError, match="invoice_date"):
        validate_dataset(dataset)


def test_ground_truth_changes_scoring_not_decisions_or_extracts(dataset):
    original = deepcopy(dataset)
    report = evaluate(dataset)
    assert dataset == original

    relabeled = deepcopy(dataset)
    invoice = next(invoice for invoice in relabeled["invoices"] if invoice["failure_mode"] == "clean")
    invoice["ground_truth"]["expected_disposition"] = "NEEDS_REVIEW"
    adjusted = evaluate(relabeled)
    for previous, current in zip(report["invoices"], adjusted["invoices"], strict=True):
        assert previous["fixture_id"] == current["fixture_id"]
        assert previous["baseline"] == current["baseline"]
        assert previous["assisted"] == current["assisted"]
    assert report["splits"]["overall"]["assisted"]["wrong_ready"] == 0
    assert adjusted["splits"]["overall"]["assisted"]["wrong_ready"] == 1


def test_review_replay_revalidates_without_changing_the_frozen_extract(dataset):
    invoice = next(invoice for invoice in dataset["invoices"] if invoice["fixture_id"] == "dev-03-digit-drop")
    extract = invoice["frozen_ocr_extract"]
    directory = dataset["supplier_directory"]
    before = deepcopy(dataset)
    original = assisted(extract, directory)
    assert original.disposition == "NEEDS_REVIEW"
    assert original.error_codes == ("ERR_LINE_TOTAL_MISMATCH",)

    corrected = replay_review(extract, directory, lines={0: {"quantity": "١٢"}})
    assert corrected.disposition == "READY"
    assert not corrected.error_codes
    assert dataset == before
    assert assisted(extract, directory) == original


def test_cli_is_deterministic_without_packages_credentials_or_network():
    root_args = [str((LAB / "run_eval.py").relative_to(ROOT)), "--fixtures", str(FIXTURES.relative_to(ROOT))]
    lab_args = ["run_eval.py", "--fixtures", str(FIXTURES.relative_to(LAB))]
    before = FIXTURES.read_bytes()
    # Python's audit hook fails the command if the replay opens a socket or a child process.
    guard = """
import pathlib
import runpy
import sys

def offline(event, _args):
    if event.startswith(("socket.", "subprocess.")):
        raise AssertionError(f"Offline replay attempted {event}")

sys.addaudithook(offline)
sys.argv = sys.argv[1:]
sys.path.insert(0, str(pathlib.Path(sys.argv[0]).resolve().parent))
runpy.run_path(sys.argv[0], run_name="__main__")
"""

    def run(arguments, cwd, seed):
        return subprocess.run(
            [sys.executable, "-B", "-S", *arguments],
            cwd=cwd,
            env={"PYTHONHASHSEED": str(seed), "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=10,
        )

    direct = run(root_args, ROOT, 1)
    guarded = run(["-c", guard, *lab_args], LAB, 2)
    assert direct.stdout == guarded.stdout
    assert not direct.stderr and not guarded.stderr
    for heading in (
        "## Dispositions",
        "## Shared raw field agreement",
        "## Date input coverage",
        "## Invoice breakdown",
        "## Reviewer walkthrough",
    ):
        assert heading in direct.stdout
    assert "dev-03-digit-drop" in direct.stdout
    assert "holdout-20-balanced-unit" in direct.stdout
    assert "python run_eval.py --fixtures fixtures/invoices_v1.json" in direct.stdout
    assert FIXTURES.read_bytes() == before
