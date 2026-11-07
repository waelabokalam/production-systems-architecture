"""Score both policies on the same frozen OCR extracts and render a Markdown report."""

import argparse
import shlex
import sys
from decimal import Decimal
from os.path import relpath
from pathlib import Path
from typing import Any

from schema import identity_key, load_dataset, validate_dataset
from validator import (
    assisted, baseline, calculated_line_sum, currency_code, parse_decimal, parse_invoice_date,
    replay_review,
)


AGREEMENT_FIELDS = ("supplier", "currency", "stated_total", "calculated_line_sum")
REPORT_SPLITS = ("overall", "dev", "holdout")
DATE_STATES = ("valid", "missing", "invalid")


def _raw_agreement(extract: dict[str, Any], truth: dict[str, str]) -> dict[str, bool]:
    try:
        stated = parse_decimal(extract["stated_total"])
    except ValueError:
        stated = None
    return {
        "supplier": identity_key(extract["supplier_name"] or "") == identity_key(truth["supplier_canonical"]),
        "currency": currency_code(extract["currency"] or "") == truth["currency"],
        "stated_total": stated == Decimal(truth["stated_total"]),
        "calculated_line_sum": calculated_line_sum(extract) == Decimal(truth["calculated_line_sum"]),
    }


def _date_status(value: str | None) -> str:
    if value is None or not value.strip():
        return "missing"
    try:
        parse_invoice_date(value)
    except ValueError:
        return "invalid"
    return "valid"


def _disposition_counts(rows: list[dict[str, Any]], method: str) -> dict[str, int | float | None]:
    ready = [row for row in rows if row[method].disposition == "READY"]
    correct_ready = sum(row["expected_disposition"] == "READY" for row in ready)
    reviews = len(rows) - len(ready)
    return {
        "ready": len(ready),
        "needs_review": reviews,
        "correct_ready": correct_ready,
        "wrong_ready": len(ready) - correct_ready,
        "review_count": reviews,
        "review_rate": reviews / len(rows) if rows else None,
    }


def evaluate(dataset: dict[str, Any]) -> dict[str, Any]:
    """Return per-invoice decisions and the aggregate metrics for each split.

    The `invoices` records contain both ValidationResults and raw agreement
    booleans. `splits` reports disposition counts, review fractions (None for
    an empty split), raw agreement `{matches, n}` per field, and counts of
    valid, missing, and invalid OCR dates. Review replay is not scored.
    """
    validate_dataset(dataset)
    directory = dataset["supplier_directory"]
    rows = []
    for fixture in dataset["invoices"]:
        extract = fixture["frozen_ocr_extract"]
        baseline_result = baseline(extract)
        assisted_result = assisted(extract, directory)
        truth = fixture["ground_truth"]  # Independent labels enter after both decisions.
        row = {
            key: fixture[key]
            for key in ("fixture_id", "template_id", "supplier_family", "split", "language", "failure_mode")
        }
        rows.append({
            **row,
            "expected_disposition": truth["expected_disposition"],
            "baseline": baseline_result,
            "assisted": assisted_result,
            "agreement": _raw_agreement(extract, truth),
            "date_status": _date_status(extract["invoice_date"]),
        })

    splits = {}
    for split in REPORT_SPLITS:
        selected = rows if split == "overall" else [row for row in rows if row["split"] == split]
        splits[split] = {
            "n": len(selected),
            "baseline": _disposition_counts(selected, "baseline"),
            "assisted": _disposition_counts(selected, "assisted"),
            "agreement": {
                field: {"matches": sum(row["agreement"][field] for row in selected), "n": len(selected)}
                for field in AGREEMENT_FIELDS
            },
            "date_coverage": {state: sum(row["date_status"] == state for row in selected) for state in DATE_STATES},
        }
    return {"splits": splits, "invoices": rows}


def _percent(rate: float | None) -> str:
    return "—" if rate is None else f"{rate:.1%}"


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _reviewer_walkthrough(dataset: dict[str, Any]) -> str:
    # Scripted reading of the synthetic source scenario, not a proposed repair
    # derived from the rule, the printed amount, or the scoring labels.
    fixture_id, reviewer_quantity = "dev-03-digit-drop", "١٢"
    fixture = next((entry for entry in dataset["invoices"] if entry["fixture_id"] == fixture_id), None)
    unavailable = "This fixture set does not contain the lab's scripted reviewer example."
    if fixture is None:
        return unavailable
    extract = fixture["frozen_ocr_extract"]
    if not extract["lines"] or extract["invoice_number"] != "SYN-D103":
        return unavailable
    line = extract["lines"][0]
    if (line["quantity"], line["unit_price"], line["line_total"]) != ("٢", "٣٬٨٠٠", "٤٥٬٦٠٠"):
        return unavailable

    directory = dataset["supplier_directory"]
    before = assisted(extract, directory)
    if not any(
        issue.code == "ERR_LINE_TOTAL_MISMATCH" and issue.path == "lines[0].line_total"
        for issue in before.issues
    ):
        return unavailable
    after = replay_review(extract, directory, lines={0: {"quantity": reviewer_quantity}})
    before_product = calculated_line_sum({"lines": [line]})
    after_product = calculated_line_sum({"lines": [{**line, "quantity": reviewer_quantity}]})
    return (
        f"`{fixture_id}` (`{extract['invoice_number']}`), line 1: frozen OCR reads quantity "
        f"`{line['quantity']}` at unit price `{line['unit_price']}`, with printed line total "
        f"`{line['line_total']}`. The rule calculates "
        f"`{parse_decimal(line['quantity'])} × {parse_decimal(line['unit_price'])} = {before_product}` "
        f"against `{parse_decimal(line['line_total'])}` and records `ERR_LINE_TOTAL_MISMATCH` "
        f"at `lines[0].line_total` (`{before.disposition}`).\n\n"
        f"The scripted reviewer transcribes `{reviewer_quantity}` from the synthetic source scenario "
        f"and changes only the draft quantity. Replay yields "
        f"`{parse_decimal(reviewer_quantity)} × {parse_decimal(line['unit_price'])} = {after_product}` "
        f"and `{after.disposition}`. The frozen extract and scores do not change."
    )


def render_report(dataset: dict[str, Any], fixtures_path: str | Path) -> str:
    """Render the exact text used for both stdout and the optional output file."""
    scores = evaluate(dataset)
    splits = scores["splits"]
    fixture_file = Path(fixtures_path).resolve()
    try:
        replay_path = relpath(fixture_file, start=Path(__file__).resolve().parent)
    except ValueError:  # An absolute path is needed across different Windows drives.
        replay_path = str(fixture_file)
    command = f"python run_eval.py --fixtures {shlex.quote(replay_path)}"
    output = [
        "# TQEN invoice reliability — synthetic evaluation", "",
        f"Both methods read the same {splits['overall']['n']} synthetic frozen OCR extracts "
        f"({splits['dev']['n']} dev, {splits['holdout']['n']} holdout). The splits share no template "
        "IDs, supplier families, or normalized canonical supplier labels. The assisted policy uses a "
        "known synthetic supplier catalog spanning both splits. No OCR runs here: this measures "
        "validation policy, not OCR accuracy, production performance, or approval authority.", "",
        "Reproduce from the lab directory:", "", "```sh", command, "```", "",
        "For the separate controlled OCR timeout and safe retry, see the [operational runbook](RUNBOOK.md).", "",
        "## Dispositions", "",
        "Correct-ready and wrong-ready are READY decisions compared with the independent "
        "expected disposition. Review rate is NEEDS_REVIEW divided by all fixtures in the split.", "",
        "| Split | Method | N | READY | Correct-ready | Wrong-ready | NEEDS_REVIEW | Review rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split in REPORT_SPLITS:
        for method in ("baseline", "assisted"):
            counts = splits[split][method]
            output.append(
                f"| {split} | {method} | {splits[split]['n']} | {counts['ready']} | "
                f"{counts['correct_ready']} | {counts['wrong_ready']} | {counts['needs_review']} | "
                f"{_percent(counts['review_rate'])} |"
            )

    output.extend([
        "", "## Shared raw field agreement", "",
        "Matches / fixtures (%), against independent labels. Missing or unparseable fields count as "
        "non-matches. Currency agreement checks the header only. Calculated line sum is numeric-only "
        "Σ(OCR quantity × OCR unit price), without checking currency consistency or applying reviewer edits.", "",
        "| Split | Supplier | Currency | Stated total | Calculated line sum |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for split in REPORT_SPLITS:
        cells = []
        for field in AGREEMENT_FIELDS:
            matches = splits[split]["agreement"][field]["matches"]
            n = splits[split]["agreement"][field]["n"]
            cells.append(f"{matches}/{n} ({_percent(matches / n if n else None)})")
        output.append(f"| {split} | " + " | ".join(cells) + " |")

    output.extend([
        "", "## Date input coverage", "",
        "Counts measure date presence and calendar validity, not agreement with a source date.", "",
        "| Split | Valid | Missing | Invalid |", "| --- | ---: | ---: | ---: |",
    ])
    for split in REPORT_SPLITS:
        counts = [str(splits[split]["date_coverage"][state]) for state in DATE_STATES]
        output.append(f"| {split} | " + " | ".join(counts) + " |")

    output.extend([
        "", "## Invoice breakdown", "",
        "| Fixture | Split / language | Failure mode | Expected | Baseline | Assisted |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in scores["invoices"]:
        outcomes = []
        for method in ("baseline", "assisted"):
            result = row[method]
            codes = ", ".join(f"`{code}`" for code in result.error_codes)
            outcomes.append(f"{result.disposition} ({codes})" if codes else result.disposition)
        output.append(
            f"| {_cell(row['fixture_id'])} | {row['split']} / {row['language']} | {row['failure_mode']} | "
            f"{row['expected_disposition']} | {outcomes[0]} | {outcomes[1]} |"
        )
    output.extend(["", "## Reviewer walkthrough", "", _reviewer_walkthrough(dataset), ""])
    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path, help="path to the synthetic fixture JSON")
    parser.add_argument("--output", type=Path, help="also write the same Markdown to this path")
    args = parser.parse_args(argv)
    try:
        if args.output is not None and (
            args.output.resolve() == args.fixtures.resolve()
            or (args.output.exists() and args.fixtures.exists() and args.output.samefile(args.fixtures))
        ):
            raise ValueError("--output must not overwrite --fixtures")
        report = render_report(load_dataset(args.fixtures), args.fixtures)
        if args.output is not None:
            args.output.write_text(report, encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
