"""Newly authored synthetic specifications, not commercial application code.

Each function models one selected boundary described in the case studies.
Database RLS, real service integrations and concurrency are outside this model.
"""

from dataclasses import dataclass
from unicodedata import normalize


def identity_key(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())


@dataclass(frozen=True)
class CatalogItem:
    identifier: str
    name: str
    unit: str


def verified_item_link(name: str, unit: str, catalog: list[CatalogItem]) -> str | None:
    """Only an exact normalized identity with a compatible unit is linked."""
    for item in catalog:
        if identity_key(name) == identity_key(item.name) and unit == item.unit:
            return item.identifier
    return None


def scope_matches(
    authenticated_org: str, requested_org: str, branch: str, allowed_branches: set[str]
) -> bool:
    return authenticated_org == requested_org and branch in allowed_branches


def case_resource_visible(
    *,
    role: str,
    actor: str,
    client: str,
    assigned: set[str],
    supervised: set[str],
    resource: str,
    active: bool = True,
) -> bool:
    """Reduced role/case projection: clients never receive internal tasks."""
    if not active:
        return False
    if role == "owner":
        return True
    if role == "client":
        return actor == client and resource == "public_progress"
    if role == "employee":
        return actor in assigned
    if role == "head_employee":
        return actor in assigned or bool(assigned & supervised)
    return False


def task_move(
    state: str, action: str, *, review_required: bool = True, authorized_reviewer: bool = False
) -> str:
    if (state, action) == ("in_progress", "submit") and review_required:
        return "pending_approval"
    if (state, action) == ("in_progress", "complete") and not review_required:
        return "done"
    if state == "pending_approval" and authorized_reviewer:
        if action == "approve":
            return "done"
        if action == "reject":
            return "in_progress"
    raise ValueError("Transition is not permitted by this reduced contract")


def can_review_plan(role: str, state: str) -> bool:
    return role == "owner" and state == "pending"


def localized_label(locale: str, english: str, arabic: str | None) -> str:
    return arabic if locale == "ar" and arabic else english
