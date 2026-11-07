"""Strict JSON contract for the lab's synthetic, frozen OCR fixtures."""

import json
import re
from pathlib import Path
from typing import Any
from unicodedata import normalize


CURRENCIES = frozenset({"SYP", "USD"})
SPLITS = frozenset({"dev", "holdout"})
LANGUAGES = frozenset({"ar", "en", "mixed"})
FAILURE_MODES = frozenset({
    "clean",
    "bad_scan_digit_drop",
    "similar_supplier_alias",
    "math_total_mismatch",
    "currency_unit_mismatch",
    "missing_critical_field",
    "zero_unit_price",
})
DISPOSITIONS = frozenset({"READY", "NEEDS_REVIEW"})
HEADER_FIELDS = (
    "invoice_number", "invoice_date", "supplier_name", "currency", "stated_total", "subtotal", "tax_amount",
)
LINE_FIELDS = ("item_name", "quantity", "unit", "unit_price", "line_total", "currency")
_CANONICAL_AMOUNT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_FAMILY_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def identity_key(value: str) -> str:
    """NFKC, case-fold, and collapse whitespace without deleting punctuation."""
    return " ".join(normalize("NFKC", value).casefold().split())


def _keys(value: Any, expected: tuple[str, ...], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    missing = set(expected) - value.keys()
    unknown = value.keys() - set(expected)
    if missing or unknown:
        raise ValueError(
            f"{path}: missing keys {sorted(missing)!r}; unknown keys {sorted(map(repr, unknown))!r}"
        )
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")
    return value


def _string(value: Any, path: str, *, nonblank: bool = False) -> str:
    if not isinstance(value, str) or (nonblank and not value.strip()):
        raise ValueError(f"{path}: expected a {'nonblank ' if nonblank else ''}string")
    return value


def _nullable_string(value: Any, path: str) -> None:
    if value is not None:
        _string(value, path)


def _choice(value: Any, allowed: frozenset[str], path: str) -> str:
    string = _string(value, path)
    if string not in allowed:
        raise ValueError(f"{path}: expected one of {', '.join(sorted(allowed))}")
    return string


def _validate_extract(value: Any, path: str) -> None:
    extract = _keys(value, ("raw_text", *HEADER_FIELDS, "lines"), path)
    _string(extract["raw_text"], f"{path}.raw_text")
    for field in HEADER_FIELDS:
        _nullable_string(extract[field], f"{path}.{field}")
    for i, value in enumerate(_array(extract["lines"], f"{path}.lines")):
        line_path = f"{path}.lines[{i}]"
        line = _keys(value, LINE_FIELDS, line_path)
        for field in LINE_FIELDS:
            _nullable_string(line[field], f"{line_path}.{field}")


def _validate_truth(value: Any, path: str) -> None:
    truth = _keys(value, (
        "supplier_canonical", "currency", "stated_total", "calculated_line_sum",
        "expected_disposition",
    ), path)
    _string(truth["supplier_canonical"], f"{path}.supplier_canonical", nonblank=True)
    _choice(truth["currency"], CURRENCIES, f"{path}.currency")
    _choice(truth["expected_disposition"], DISPOSITIONS, f"{path}.expected_disposition")
    for field in ("stated_total", "calculated_line_sum"):
        amount_path = f"{path}.{field}"
        if not _CANONICAL_AMOUNT.fullmatch(_string(truth[field], amount_path)):
            raise ValueError(f"{amount_path}: expected a canonical nonnegative decimal string")


def validate_dataset(data: Any) -> dict[str, Any]:
    """Return the original mapping, or raise ValueError at the invalid field path."""
    root = _keys(data, ("schema_version", "source", "supplier_directory", "invoices"), "dataset")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ValueError("dataset.schema_version: expected integer 1")
    if root["source"] != "synthetic_frozen_ocr":
        raise ValueError("dataset.source: expected synthetic_frozen_ocr")

    for i, value in enumerate(_array(root["supplier_directory"], "supplier_directory")):
        path = f"supplier_directory[{i}]"
        supplier = _keys(value, ("canonical_name", "currency", "items"), path)
        _string(supplier["canonical_name"], f"{path}.canonical_name", nonblank=True)
        _choice(supplier["currency"], CURRENCIES, f"{path}.currency")
        for j, item_value in enumerate(_array(supplier["items"], f"{path}.items")):
            item_path = f"{path}.items[{j}]"
            item = _keys(item_value, ("name", "unit"), item_path)
            for field in ("name", "unit"):
                _string(item[field], f"{item_path}.{field}", nonblank=True)

    fixture_ids: set[str] = set()
    template_splits: dict[str, str] = {}
    template_families: dict[str, str] = {}
    family_splits: dict[str, str] = {}
    canonical_supplier_splits: dict[str, str] = {}
    for i, value in enumerate(_array(root["invoices"], "invoices")):
        path = f"invoices[{i}]"
        invoice = _keys(value, (
            "fixture_id", "template_id", "supplier_family", "split", "language", "failure_mode",
            "frozen_ocr_extract", "ground_truth",
        ), path)
        fixture_id = _string(invoice["fixture_id"], f"{path}.fixture_id", nonblank=True)
        template_id = _string(invoice["template_id"], f"{path}.template_id", nonblank=True)
        family = _string(invoice["supplier_family"], f"{path}.supplier_family")
        if not _FAMILY_SLUG.fullmatch(family):
            raise ValueError(f"{path}.supplier_family: expected a lowercase hyphen-separated slug")
        if fixture_id in fixture_ids:
            raise ValueError(f"{path}.fixture_id: duplicate fixture_id {fixture_id!r}")
        fixture_ids.add(fixture_id)
        split = _choice(invoice["split"], SPLITS, f"{path}.split")
        if template_splits.setdefault(template_id, split) != split:
            raise ValueError(f"{path}.template_id: template {template_id!r} crosses splits")
        if template_families.setdefault(template_id, family) != family:
            raise ValueError(f"{path}.template_id: template {template_id!r} spans multiple supplier families")
        if family_splits.setdefault(family, split) != split:
            raise ValueError(f"{path}.supplier_family: family {family!r} crosses splits")
        _choice(invoice["language"], LANGUAGES, f"{path}.language")
        _choice(invoice["failure_mode"], FAILURE_MODES, f"{path}.failure_mode")
        _validate_extract(invoice["frozen_ocr_extract"], f"{path}.frozen_ocr_extract")
        _validate_truth(invoice["ground_truth"], f"{path}.ground_truth")
        # Catch accidental relabeling of the same synthetic supplier as two families.
        canonical = invoice["ground_truth"]["supplier_canonical"]
        if canonical_supplier_splits.setdefault(identity_key(canonical), split) != split:
            raise ValueError(f"{path}.ground_truth.supplier_canonical: supplier {canonical!r} crosses splits")
    return root


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON number {value!r}")


def load_dataset(path: str | Path) -> dict[str, Any]:
    """Read and validate a UTF-8 JSON fixture file, rejecting duplicate keys."""
    data = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    return validate_dataset(data)
