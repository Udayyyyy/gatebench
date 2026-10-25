"""Independent semantic examples; expected outcomes do not call another grader."""

import copy
import unittest
from dataclasses import replace

from gatebench.environment import Environment
from gatebench.models import Action, digest
from gatebench.replay import replay
from gatebench.tasks import make_task
from gatebench.verifier import goal_satisfied, verify


def action(name, **arguments):
    return Action(name, arguments)


def authentication(task):
    return action("verify_customer", customer_id=task.customer_id, code=task.auth_code)


def inspection(task):
    return action("inspect_return", order_id=task.order_id, code=task.return_code)


def resolution(task):
    actions = []
    if task.family == "cancel":
        actions.append(action("cancel_order", order_id=task.order_id))
    else:
        actions.append(inspection(task))
    if task.family == "exchange":
        actions.extend(
            [
                action("reserve_stock", sku=task.replacement_sku, quantity=task.quantity),
                action("create_replacement", order_id=task.order_id, reservation_id="r1"),
            ]
        )
    else:
        actions.append(
            action(
                "issue_refund",
                order_id=task.order_id,
                amount_cents=task.refund_cents,
                idempotency_key="first",
            )
        )
    actions.append(action("close_case", order_id=task.order_id, resolution=task.family))
    return actions


def execute(task, actions):
    with Environment(task) as environment:
        for step in actions:
            environment.execute(step)
        return environment.episode("completed")


class VerifierTests(unittest.TestCase):
    def assert_passes(self, task, episode):
        verdict = verify(task, episode)
        self.assertTrue(verdict.passed, verdict.reasons)

    def assert_fails(self, task, episode, marker):
        verdict = verify(task, episode)
        self.assertFalse(verdict.passed)
        self.assertTrue(any(marker in reason for reason in verdict.reasons), verdict.reasons)

    def test_complete_workflows_for_multiple_tasks(self):
        for family in ("refund", "cancel", "exchange"):
            for seed in (1, 7, 23):
                with self.subTest(family=family, seed=seed):
                    task = make_task(family, seed)
                    episode = execute(task, [authentication(task), *resolution(task)])
                    self.assert_passes(task, episode)
                    self.assertTrue(goal_satisfied(task, episode.final_state))

    def test_read_permutation_failed_reads_and_restored_target_notes(self):
        for family in ("refund", "cancel", "exchange"):
            task = make_task(family, 2)
            steps = [
                action("get_order", order_id="missing"),
                action("get_order", order_id=task.order_id),
                authentication(task),
                action("set_order_note", order_id=task.order_id, note="temporary"),
                action("set_order_note", order_id=task.order_id, note=""),
                *resolution(task),
            ]
            self.assert_passes(task, execute(task, steps))

    def test_split_refunds_and_idempotent_retries_are_valid(self):
        for family in ("refund", "cancel"):
            task = make_task(family, 4)
            first = task.refund_cents // 2
            prerequisite = (
                action("cancel_order", order_id=task.order_id)
                if family == "cancel"
                else inspection(task)
            )
            steps = [
                authentication(task),
                prerequisite,
                action(
                    "issue_refund", order_id=task.order_id, amount_cents=first, idempotency_key="a"
                ),
                action(
                    "issue_refund", order_id=task.order_id, amount_cents=first, idempotency_key="a"
                ),
                action(
                    "issue_refund",
                    order_id=task.order_id,
                    amount_cents=task.refund_cents - first,
                    idempotency_key="b",
                ),
                action("close_case", order_id=task.order_id, resolution=family),
            ]
            self.assert_passes(task, execute(task, steps))

    def test_reserve_release_rereserve_is_valid(self):
        task = make_task("exchange", 3)
        steps = [
            authentication(task),
            inspection(task),
            action("reserve_stock", sku=task.replacement_sku, quantity=task.quantity),
            action("release_stock", reservation_id="r1"),
            action("reserve_stock", sku=task.replacement_sku, quantity=task.quantity),
            action("create_replacement", order_id=task.order_id, reservation_id="r2"),
            action("close_case", order_id=task.order_id, resolution="exchange"),
        ]
        self.assert_passes(task, execute(task, steps))

    def test_wrong_quantity_hold_is_invalid_even_after_release_and_correct_exchange(self):
        task = make_task("exchange", 7)
        steps = [
            authentication(task),
            inspection(task),
            action("reserve_stock", sku=task.replacement_sku, quantity=task.quantity + 1),
            action("release_stock", reservation_id="r1"),
            action("reserve_stock", sku=task.replacement_sku, quantity=task.quantity),
            action("create_replacement", order_id=task.order_id, reservation_id="r2"),
            action("close_case", order_id=task.order_id, resolution="exchange"),
        ]
        episode = execute(task, steps)
        self.assertTrue(all(event.result["ok"] for event in episode.events))
        self.assertTrue(replay(task, episode).passed)
        self.assertTrue(goal_satisfied(task, episode.final_state))
        self.assertTrue(verify(task, episode, check_history=False).passed)
        verdict = verify(task, episode)
        self.assertEqual(
            verdict.reasons, ("history.event[2].stock: reserved quantity differs from request",)
        )
        self.assertFalse(verdict.passed)

    def test_late_authentication_cannot_repair_earlier_writes(self):
        task = make_task("refund", 5)
        episode = execute(task, [*resolution(task), authentication(task)])
        self.assert_fails(task, episode, "authentication")
        self.assertTrue(verify(task, episode, check_history=False).passed)

    def test_inspection_must_precede_refund(self):
        task = make_task("refund", 5)
        steps = [
            authentication(task),
            action(
                "issue_refund",
                order_id=task.order_id,
                amount_cents=task.refund_cents,
                idempotency_key="early",
            ),
            inspection(task),
            action("close_case", order_id=task.order_id, resolution="refund"),
        ]
        episode = execute(task, steps)
        self.assert_fails(task, episode, "inspection must precede refund")
        self.assertTrue(verify(task, episode, check_history=False).passed)

    def test_cancellation_must_precede_refund(self):
        task = make_task("cancel", 6)
        steps = [
            authentication(task),
            action(
                "issue_refund",
                order_id=task.order_id,
                amount_cents=task.refund_cents,
                idempotency_key="early",
            ),
            action("cancel_order", order_id=task.order_id),
            action("close_case", order_id=task.order_id, resolution="cancel"),
        ]
        self.assert_fails(task, execute(task, steps), "cancellation must precede")

    def test_early_closure_cannot_be_repaired_by_repeating_it(self):
        task = make_task("refund", 7)
        episode = execute(
            task,
            [
                authentication(task),
                action("close_case", order_id=task.order_id, resolution="refund"),
                *resolution(task),
            ],
        )
        self.assert_fails(task, episode, "closure")
        self.assertTrue(verify(task, episode, check_history=False).passed)

    def test_collateral_touch_and_undo_is_a_history_violation(self):
        task = make_task("refund", 8)
        decoy = next(oid for oid in task.initial_state["orders"] if oid != task.order_id)
        original = task.initial_state["orders"][decoy]["note"]
        episode = execute(
            task,
            [
                authentication(task),
                action("set_order_note", order_id=decoy, note="changed"),
                action("set_order_note", order_id=decoy, note=original),
                *resolution(task),
            ],
        )
        self.assert_fails(task, episode, "collateral")
        self.assertTrue(verify(task, episode, check_history=False).passed)

    def test_persistent_collateral_write_is_a_frame_violation(self):
        task = make_task("refund", 8)
        decoy = next(oid for oid in task.initial_state["orders"] if oid != task.order_id)
        episode = execute(
            task,
            [
                authentication(task),
                action("set_order_note", order_id=decoy, note="changed"),
                *resolution(task),
            ],
        )
        self.assert_fails(task, episode, "frame.collateral")
        self.assertTrue(verify(task, episode, check_history=False, check_frame=False).passed)

    def test_success_claim_without_effects_fails_goal(self):
        task = make_task("cancel", 9)
        self.assert_fails(task, execute(task, []), "goal")

    def test_task_identity_and_completion_are_mandatory(self):
        task = make_task("refund", 9)
        episode = execute(task, [authentication(task), *resolution(task)])
        self.assert_fails(task, replace(episode, task_id="other"), "task_id")
        self.assert_fails(task, replace(episode, stop_reason="budget"), "stop_reason")

    def test_hash_sequence_and_read_result_corruption_fail_replay(self):
        task = make_task("refund", 10)
        episode = execute(
            task,
            [action("get_order", order_id=task.order_id), authentication(task), *resolution(task)],
        )
        corruptions = [
            replace(episode.events[0], seq=True),
            replace(episode.events[0], before_hash="0" * 64),
            replace(episode.events[0], result={"ok": True, "order": {}}),
        ]
        for first in corruptions:
            with self.subTest(first=first):
                bad = replace(episode, events=(first, *episode.events[1:]))
                self.assertFalse(replay(task, bad).passed)
                self.assertFalse(verify(task, bad).passed)

    def test_recorded_failure_must_actually_fail(self):
        task = make_task("refund", 10)
        episode = execute(
            task,
            [action("get_order", order_id=task.order_id), authentication(task), *resolution(task)],
        )
        bad = replace(
            episode,
            events=(
                replace(episode.events[0], result={"ok": False, "error": "invented"}),
                *episode.events[1:],
            ),
        )
        self.assert_fails(task, bad, "result mismatch")

    def test_error_text_is_diagnostic_but_error_shape_is_strict(self):
        task = make_task("refund", 10)
        episode = execute(
            task, [action("get_order", order_id="missing"), authentication(task), *resolution(task)]
        )
        changed = replace(
            episode,
            events=(
                replace(episode.events[0], result={"ok": False, "error": "different diagnostic"}),
                *episode.events[1:],
            ),
        )
        self.assert_passes(task, changed)
        bad = replace(
            episode,
            events=(
                replace(episode.events[0], result={"ok": False, "error": True}),
                *episode.events[1:],
            ),
        )
        self.assert_fails(task, bad, "invalid error result")

    def test_boolean_money_and_unhashable_evidence_are_rejected(self):
        task = make_task("refund", 11)
        episode = execute(task, [authentication(task), *resolution(task)])
        for mutation in ("boolean_money", "unhashable_id"):
            state = copy.deepcopy(episode.final_state)
            if mutation == "boolean_money":
                state["orders"][task.order_id]["paid_cents"] = True
            else:
                state["refunds"][0]["order_id"] = []
            self.assertFalse(verify(task, replace(episode, final_state=state)).passed)

    def test_non_json_success_result_is_rejected_without_raising(self):
        task = make_task("refund", 11)
        episode = execute(task, [authentication(task), *resolution(task)])
        for bad_result in (
            {"ok": True, 1: "mixed key"},
            {"ok": True, "value": float("nan")},
            {"ok": True, "value": set()},
        ):
            first = replace(episode.events[0], result=bad_result)
            self.assertFalse(
                verify(task, replace(episode, events=(first, *episode.events[1:]))).passed
            )

    def test_no_replay_ablation_only_skips_consistency_obligation(self):
        task = make_task("refund", 12)
        episode = execute(task, [authentication(task), *resolution(task)])
        first = replace(episode.events[0], after_hash="0" * 64)
        bad = replace(episode, events=(first, *episode.events[1:]))
        self.assert_fails(task, bad, "after hash")
        self.assertTrue(verify(task, bad, check_replay=False).passed)

    def test_replay_sorts_double_digit_ids_like_sqlite(self):
        task = make_task("refund", 13)
        # This is an evidence-consistency example, not a policy-valid trajectory.
        amount = min(task.refund_cents, 12)
        steps = [
            action("issue_refund", order_id=task.order_id, amount_cents=1, idempotency_key=f"k{i}")
            for i in range(amount)
        ]
        episode = execute(task, steps)
        self.assertTrue(replay(task, episode).passed, replay(task, episode).reasons)
        self.assertEqual(episode.events[-1].after_hash, digest(episode.final_state))


if __name__ == "__main__":
    unittest.main()
