import unittest

from examples.boundary_contracts import (
    CatalogItem,
    can_review_plan,
    case_resource_visible,
    localized_label,
    scope_matches,
    task_move,
    verified_item_link,
)


class BoundaryContracts(unittest.TestCase):
    def test_normalized_exact_item_can_link(self):
        catalog = [CatalogItem("synthetic-item", "Example Flour", "kg")]
        self.assertEqual(verified_item_link("  EXAMPLE   FLOUR ", "kg", catalog), "synthetic-item")

    def test_incompatible_unit_cannot_link(self):
        self.assertIsNone(
            verified_item_link("Example Flour", "bag", [CatalogItem("example", "Example Flour", "kg")])
        )

    def test_fuzzy_name_does_not_authorize_identity(self):
        self.assertIsNone(
            verified_item_link("Example Flours", "kg", [CatalogItem("example", "Example Flour", "kg")])
        )

    def test_other_organization_is_denied(self):
        self.assertFalse(scope_matches("example-org-a", "example-org-b", "branch", {"branch"}))

    def test_unassigned_branch_is_denied(self):
        self.assertFalse(scope_matches("example-org", "example-org", "other-branch", {"branch"}))

    def test_matching_organization_and_branch_pass(self):
        self.assertTrue(scope_matches("example-org", "example-org", "branch", {"branch"}))

    def view(self, **changes):
        values = dict(
            role="client",
            actor="synthetic-client",
            client="synthetic-client",
            assigned=set(),
            supervised=set(),
            resource="public_progress",
        )
        return case_resource_visible(**(values | changes))

    def test_client_sees_own_progress(self):
        self.assertTrue(self.view())

    def test_client_cannot_see_internal_task(self):
        self.assertFalse(self.view(resource="internal_task"))

    def test_other_client_is_denied(self):
        self.assertFalse(self.view(actor="different-client"))

    def test_employee_needs_assignment(self):
        self.assertFalse(self.view(role="employee", actor="employee"))
        self.assertTrue(self.view(role="employee", actor="employee", assigned={"employee"}))

    def test_inactive_owner_is_denied(self):
        self.assertFalse(self.view(role="owner", active=False))

    def test_completion_cannot_skip_required_review(self):
        with self.assertRaises(ValueError):
            task_move("in_progress", "complete", review_required=True)

    def test_reviewer_approval_completes(self):
        self.assertEqual(task_move("pending_approval", "approve", authorized_reviewer=True), "done")

    def test_unprivileged_approval_is_denied(self):
        with self.assertRaises(ValueError):
            task_move("pending_approval", "approve")

    def test_rejection_returns_work_for_correction(self):
        self.assertEqual(task_move("pending_approval", "reject", authorized_reviewer=True), "in_progress")

    def test_kitchen_cannot_approve_commercial_request(self):
        self.assertFalse(can_review_plan("kitchen", "pending"))
        self.assertTrue(can_review_plan("owner", "pending"))
        self.assertFalse(can_review_plan("owner", "approved"))

    def test_arabic_label_and_english_fallback(self):
        self.assertEqual(localized_label("ar", "Example meal", "وجبة تجريبية"), "وجبة تجريبية")
        self.assertEqual(localized_label("ar", "Example meal", None), "Example meal")


if __name__ == "__main__":
    unittest.main()
