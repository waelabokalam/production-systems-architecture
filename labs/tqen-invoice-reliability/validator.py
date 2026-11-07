"""Provider-free invoice decisions over an OCR extract and a synthetic directory.

Identity and unit matching model the public TQEN boundary. The lab adds explicit
completeness, currency, and arithmetic rules; none of these functions see labels.
"""

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, localcontext
from difflib import SequenceMatcher
from typing import Any

from schema import CURRENCIES, HEADER_FIELDS, LINE_FIELDS, identity_key


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_AMOUNT = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:٬[0-9]{3})+)(?:[.٫][0-9]+)?")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MAX_DIGITS = 64
_FUZZY_THRESHOLD = 0.8
_UNIT_ALIASES = {
    "kg": ("kg", "kilogram", "kilograms", "كغ", "كجم", "كغم", "كيلوغرام", "كيلو غرام", "كيلوجرام"),
    "g": ("g", "gram", "grams", "غ", "غرام", "جرام", "جم"),
    "l": ("l", "liter", "litre", "liters", "litres", "ل", "لتر"),
    "ml": ("ml", "milliliter", "millilitre", "milliliters", "millilitres", "مل", "ملليلتر", "مليلتر"),
    "box": ("box", "boxes", "صندوق", "صناديق"),
    "carton": ("carton", "cartons", "كرتون", "كرتونة"),
    "piece": ("piece", "pieces", "pc", "pcs", "قطعة", "قطع"),
}
_UNIT_KEYS = {alias: canonical for canonical, aliases in _UNIT_ALIASES.items() for alias in aliases}


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[Issue, ...] = ()
    supplier_candidates: tuple[str, ...] = ()

    @property
    def disposition(self) -> str:
        return "NEEDS_REVIEW" if self.issues else "READY"

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(issue.code for issue in self.issues))


def currency_code(value: str) -> str | None:
    code = identity_key(value).upper()
    return code if code in CURRENCIES else None


def parse_decimal(value: str) -> Decimal:
    """Read an unsigned fixed-point token using an explicit digit/separator allowlist.

    Only U+066C is a grouping mark, with exactly three digits per group after
    the first. Dot and U+066B are decimal marks. No inferred comma locale,
    signs, exponents, separators in the fraction, or internal whitespace.
    """
    if not isinstance(value, str):
        raise ValueError("expected a decimal string")
    token = value.strip().translate(_DIGITS)
    if not _AMOUNT.fullmatch(token):
        raise ValueError("expected an unsigned fixed-point amount with explicit separators")
    token = token.replace("٬", "").replace("٫", ".")
    if len(token.replace(".", "")) > _MAX_DIGITS:
        raise ValueError(f"at most {_MAX_DIGITS} digits are allowed")
    return Decimal(token)


def parse_invoice_date(value: str) -> date:
    """Read a calendar-valid YYYY-MM-DD with ASCII, Arabic-Indic, or Persian digits."""
    if not isinstance(value, str):
        raise ValueError("expected a date string")
    token = value.strip().translate(_DIGITS)
    if not _ISO_DATE.fullmatch(token):
        raise ValueError("expected a zero-padded YYYY-MM-DD date")
    try:
        return date.fromisoformat(token)
    except ValueError as error:
        raise ValueError("invalid calendar date") from error


def _sum_exact(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(0)
    parts = [value.as_tuple() for value in values]
    integer_width = max(len(part.digits) + part.exponent for part in parts)
    fraction_width = max(0, -min(part.exponent for part in parts))
    # Include enough headroom for carries even if every value is the maximum.
    precision = max(1, integer_width + fraction_width) + len(str(len(values)))
    with localcontext(Context(prec=precision)):
        return sum(values, Decimal(0))


def _multiply_exact(quantity: Decimal, price: Decimal) -> Decimal:
    precision = len(quantity.as_tuple().digits) + len(price.as_tuple().digits)
    with localcontext(Context(prec=precision)):
        return quantity * price


def calculated_line_sum(extract: dict[str, Any]) -> Decimal | None:
    """Shared raw-field metric: sum OCR quantity × OCR unit price, or no value."""
    if not extract["lines"]:
        return None
    products = []
    for line in extract["lines"]:
        try:
            quantity = parse_decimal(line["quantity"])
            price = parse_decimal(line["unit_price"])
        except ValueError:
            return None
        if quantity <= 0:
            return None
        products.append(_multiply_exact(quantity, price))
    return _sum_exact(products)


def _required_text(
    record: dict[str, Any], key: str, path: str, issues: list[Issue],
) -> str | None:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(Issue("ERR_MISSING_FIELD", path, "required text is missing"))
        return None
    return value


def _number(value: str | None, path: str, issues: list[Issue], *, positive: bool = False) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = parse_decimal(value)
        if positive and amount <= 0:
            raise ValueError("must be greater than zero")
    except ValueError as error:
        issues.append(Issue("ERR_INVALID_NUMBER", path, str(error)))
        return None
    return amount


def _currency(value: str | None, path: str, issues: list[Issue]) -> str | None:
    if value is None:
        return None
    code = currency_code(value)
    if code is None:
        issues.append(Issue("ERR_CURRENCY_CONFLICT", path, "currency must be SYP or USD"))
    return code


def _supplier(
    name: str | None, directory: list[dict[str, Any]], issues: list[Issue],
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    if name is None:
        return None, ()
    key = identity_key(name)
    entries = [(identity_key(supplier["canonical_name"]), supplier) for supplier in directory]
    exact = [supplier for candidate_key, supplier in entries if candidate_key == key]
    if len(exact) == 1:
        return exact[0], ()
    if exact:
        issues.append(Issue("ERR_SUPPLIER_AMBIGUOUS", "supplier_name", "multiple exact identities"))
        return None, tuple(sorted(supplier["canonical_name"] for supplier in exact))

    ranked = sorted(
        (-SequenceMatcher(None, key, candidate_key, autojunk=False).ratio(), supplier["canonical_name"])
        for candidate_key, supplier in entries
    )
    candidates = tuple(name for score, name in ranked if -score >= _FUZZY_THRESHOLD)[:3]
    if candidates:
        issues.append(Issue("ERR_SUPPLIER_AMBIGUOUS", "supplier_name", "near name is not an exact identity"))
    else:
        issues.append(Issue("ERR_SUPPLIER_UNKNOWN", "supplier_name", "no exact identity in directory"))
    return None, candidates


def _check_item(
    name: str | None, unit: str | None, path: str, supplier: dict[str, Any] | None, issues: list[Issue],
) -> None:
    unit_key = _UNIT_KEYS.get(identity_key(unit)) if unit is not None else None
    if unit is not None and unit_key is None:
        issues.append(Issue("ERR_UNIT_CONFLICT", f"{path}.unit", "unrecognized unit"))
    if name is None or supplier is None:
        return
    matches = [item for item in supplier["items"] if identity_key(item["name"]) == identity_key(name)]
    if not matches:
        issues.append(Issue("ERR_ITEM_UNKNOWN", f"{path}.item_name", "no exact item for supplier"))
    elif unit_key is not None:
        compatible = [item for item in matches if _UNIT_KEYS.get(identity_key(item["unit"])) == unit_key]
        if not compatible:
            issues.append(Issue("ERR_UNIT_CONFLICT", f"{path}.unit", "unit does not match supplier item"))
        elif len(compatible) > 1:
            issues.append(Issue("ERR_ITEM_AMBIGUOUS", f"{path}.item_name", "multiple exact item/unit matches"))


def baseline(extract: dict[str, Any]) -> ValidationResult:
    """OCR passthrough baseline: ready if its three minimal text fields exist."""
    issues: list[Issue] = []
    for key in ("raw_text", "invoice_number", "supplier_name"):
        _required_text(extract, key, key, issues)
    return ValidationResult(tuple(issues))


def assisted(extract: dict[str, Any], directory: list[dict[str, Any]]) -> ValidationResult:
    """Evaluate the full review gate without repairing, linking, or persisting data."""
    issues: list[Issue] = []
    header = {
        key: _required_text(extract, key, key, issues)
        for key in ("raw_text", *HEADER_FIELDS)
    }
    if header["invoice_date"] is not None:
        try:
            parse_invoice_date(header["invoice_date"])
        except ValueError as error:
            issues.append(Issue("ERR_INVALID_DATE", "invoice_date", str(error)))
    supplier, candidates = _supplier(header["supplier_name"], directory, issues)
    invoice_currency = _currency(header["currency"], "currency", issues)
    supplier_currency = supplier["currency"] if supplier is not None else None
    if invoice_currency and supplier_currency and invoice_currency != supplier_currency:
        issues.append(Issue("ERR_CURRENCY_CONFLICT", "currency", "invoice and supplier currencies differ"))

    stated = _number(header["stated_total"], "stated_total", issues)
    subtotal = _number(header["subtotal"], "subtotal", issues)
    tax = _number(header["tax_amount"], "tax_amount", issues)
    if stated is not None and subtotal is not None and tax is not None:
        if _sum_exact([subtotal, tax]) != stated:
            issues.append(Issue("ERR_TOTAL_MISMATCH", "stated_total", "subtotal plus tax does not equal total"))

    lines = extract.get("lines")
    if not lines:
        issues.append(Issue("ERR_MISSING_FIELD", "lines", "at least one line is required"))
        return ValidationResult(tuple(issues), candidates)

    printed_line_totals = []
    for index, line in enumerate(lines):
        path = f"lines[{index}]"
        fields = {key: _required_text(line, key, f"{path}.{key}", issues) for key in LINE_FIELDS}
        _check_item(fields["item_name"], fields["unit"], path, supplier, issues)
        line_currency = _currency(fields["currency"], f"{path}.currency", issues)
        if line_currency and any(code and code != line_currency for code in (invoice_currency, supplier_currency)):
            issues.append(Issue("ERR_CURRENCY_CONFLICT", f"{path}.currency", "line currency differs from invoice or supplier"))

        quantity = _number(fields["quantity"], f"{path}.quantity", issues, positive=True)
        price = _number(fields["unit_price"], f"{path}.unit_price", issues, positive=True)
        total = _number(fields["line_total"], f"{path}.line_total", issues)
        if total is not None:
            printed_line_totals.append(total)
            if quantity is not None and price is not None and _multiply_exact(quantity, price) != total:
                issues.append(Issue("ERR_LINE_TOTAL_MISMATCH", f"{path}.line_total", "quantity times price does not equal line total"))

    if subtotal is not None and len(printed_line_totals) == len(lines):
        if _sum_exact(printed_line_totals) != subtotal:
            issues.append(Issue("ERR_SUBTOTAL_MISMATCH", "subtotal", "printed line totals do not sum to subtotal"))
    return ValidationResult(tuple(issues), candidates)


def replay_review(
    extract: dict[str, Any], directory: list[dict[str, Any]], *,
    header: dict[str, str | None] | None = None,
    lines: dict[int, dict[str, str | None]] | None = None,
) -> ValidationResult:
    """Apply explicit reviewer edits to a copy and re-run the gate; keep raw evidence."""
    draft = deepcopy(extract)

    def apply_fields(target: dict[str, Any], edits: dict[str, str | None], allowed: tuple[str, ...]) -> None:
        for field, value in edits.items():
            if field not in allowed or (value is not None and not isinstance(value, str)):
                raise ValueError(f"invalid reviewer edit for {field!r}")
            target[field] = value

    if header is not None:
        apply_fields(draft, header, HEADER_FIELDS)
    if lines is not None:
        for index, edits in lines.items():
            if type(index) is not int or not 0 <= index < len(draft["lines"]):
                raise ValueError(f"invalid reviewer line index {index!r}")
            apply_fields(draft["lines"][index], edits, LINE_FIELDS)
    return assisted(draft, directory)
