"""Exercise the HTTP transport with a test server, not a real model evaluation."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from gatebench import ollama
from gatebench.baselines import reference_plan
from gatebench.models import Action
from gatebench.ollama import MAX_RESPONSE, run_model
from gatebench.tasks import make_task
from gatebench.verifier import goal_satisfied, verify


def assistant(*actions, content=""):
    message = {"role": "assistant", "content": content}
    if actions:
        message["tool_calls"] = [
            {"function": {"name": action.name, "arguments": action.arguments}} for action in actions
        ]
    return {"message": message, "done": True, "done_reason": "stop"}


@contextmanager
def model_server(responses):
    """A real localhost HTTP server with explicit scripted response bodies."""
    queued = list(responses)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(
                {
                    "path": self.path,
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            response = (
                queued.pop(0) if queued else (500, {"error": "test response queue exhausted"})
            )
            if callable(response):
                response = response()
            status, payload = response if isinstance(response, tuple) else (200, response)
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when testing a caller-side timeout.

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


@pytest.mark.parametrize("family", ["refund", "cancel", "exchange"])
def test_multiturn_transport_executes_tools_and_preserves_evidence(family):
    task = make_task(family, 10002, "eval")
    plan = reference_plan(task)
    replies = [assistant(action) for action in plan] + [assistant(content="Request completed.")]
    with model_server(replies) as (endpoint, requests):
        episode, record = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert verify(task, episode).passed
    assert episode.stop_reason == "completed"
    assert [event.action for event in episode.events] == plan
    assert len(requests) == len(plan) + 1
    assert all(request["path"] == "/api/chat" for request in requests)
    assert len(record["responses"]) == len(replies)
    assert requests[1]["body"]["messages"][-1]["role"] == "tool"
    assert json.loads(requests[1]["body"]["messages"][-1]["content"])["ok"] is True
    assert requests[0]["body"]["stream"] is False
    assert requests[0]["body"]["options"]["seed"] == 17
    assert record["kind"] == "model_trial"
    assert record["task_fingerprint"] == task.fingerprint
    assert "error" not in record


def test_multiple_tools_in_one_response_are_executed_in_order():
    task = make_task("exchange", 10009, "eval")
    plan = reference_plan(task)
    with model_server([assistant(*plan), assistant(content="Done.")]) as (endpoint, requests):
        episode, _ = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert verify(task, episode).passed
    assert len(requests) == 2
    assert [event.action for event in episode.events] == plan


def test_tool_errors_are_returned_to_the_model_and_can_be_recovered():
    task = make_task("refund", 10007, "eval")
    bad = Action("verify_customer", {"customer_id": task.customer_id, "code": "wrong-code"})
    with model_server(
        [assistant(bad), assistant(*reference_plan(task)), assistant(content="Completed.")]
    ) as (endpoint, requests):
        episode, _ = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert episode.events[0].result["ok"] is False
    assert json.loads(requests[1]["body"]["messages"][-1]["content"])["ok"] is False
    assert verify(task, episode).passed


def test_tool_budget_caps_a_multicall_response_without_executing_the_rest():
    task = make_task("refund", 1)
    read = Action("get_order", {"order_id": task.order_id})
    with model_server([assistant(*([read] * 10))]) as (endpoint, requests):
        episode, record = run_model(
            task, model="scripted-http-test", endpoint=endpoint, max_steps=2
        )
    assert episode.stop_reason == "budget"
    assert len(episode.events) == record["tool_calls"] == 2
    assert len(requests) == 1
    assert not verify(task, episode).passed


def test_workflow_using_exact_tool_budget_can_still_finish_with_a_summary():
    task = make_task("refund", 1)
    plan = reference_plan(task)
    with model_server([assistant(*plan), assistant(content="Request completed.")]) as (
        endpoint,
        requests,
    ):
        episode, record = run_model(
            task, model="scripted-http-test", endpoint=endpoint, max_steps=len(plan)
        )
    assert len(episode.events) == record["tool_calls"] == len(plan)
    assert len(requests) == 2
    assert episode.stop_reason == "completed"
    assert verify(task, episode).passed


def test_truncated_generation_is_a_budget_stop_even_after_the_workflow_finishes():
    task = make_task("refund", 1)
    truncated = assistant(content="I completed the request and")
    truncated["done_reason"] = "length"
    with model_server([assistant(*reference_plan(task)), truncated]) as (endpoint, _):
        episode, record = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert record["responses"][-1]["done_reason"] == "length"
    assert episode.stop_reason == "budget"
    assert not verify(task, episode).passed


def test_final_response_arriving_after_deadline_cannot_complete_the_episode(monkeypatch):
    task = make_task("refund", 1)
    plan = reference_plan(task)
    late_response = threading.Event()

    def clock():
        return 103.0 if late_response.is_set() else 100.0

    def deliver_after_deadline():
        late_response.set()
        return assistant(content="Request completed.")

    # Advance only this adapter's clock when the HTTP handler serves the final
    # response. This exercises the real transport without a timing-sensitive sleep.
    monkeypatch.setattr(ollama, "time", SimpleNamespace(monotonic=clock))
    with model_server([assistant(*plan), deliver_after_deadline]) as (endpoint, requests):
        episode, record = run_model(task, model="scripted-http-test", endpoint=endpoint, deadline=2)
    assert len(requests) == len(record["responses"]) == 2
    assert len(episode.events) == len(plan)
    assert goal_satisfied(task, episode.final_state)
    assert record["deadline_exceeded"] is True
    assert episode.stop_reason == "budget"
    assert not verify(task, episode).passed


def test_turn_budget_stops_an_agent_that_keeps_reading():
    task = make_task("cancel", 1)
    read = Action("get_order", {"order_id": task.order_id})
    with model_server([assistant(read)] * 5) as (endpoint, requests):
        episode, _ = run_model(task, model="scripted-http-test", endpoint=endpoint, max_turns=2)
    assert episode.stop_reason == "budget"
    assert len(episode.events) == len(requests) == 2


def test_timeout_preserves_partial_evidence_and_returns_an_error():
    task = make_task("refund", 1)

    def delayed_response():
        threading.Event().wait(0.15)
        return assistant(content="Completed.")

    with model_server([delayed_response]) as (endpoint, _):
        episode, record = run_model(
            task, model="scripted-http-test", endpoint=endpoint, timeout=0.02
        )
    assert episode.stop_reason == "error"
    assert "timed out" in record["error"].lower()
    assert not episode.events


def test_transport_error_retains_tools_already_executed():
    task = make_task("cancel", 1)
    auth = Action("verify_customer", {"customer_id": task.customer_id, "code": task.auth_code})
    with model_server([assistant(auth), (503, {"error": "unavailable"})]) as (endpoint, _):
        episode, record = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert episode.stop_reason == "error"
    assert len(episode.events) == record["tool_calls"] == 1
    assert episode.events[0].action == auth
    assert episode.final_state["verified_customers"] == [task.customer_id]
    assert len(record["responses"]) == 1
    assert not verify(task, episode).passed


@pytest.mark.parametrize(
    "response",
    [
        (500, {"error": "service unavailable"}),
        (200, b"not JSON"),
        [],
        {"message": {"role": "user", "content": "wrong role"}},
        {"message": {"role": "assistant", "content": []}},
        {"message": {"role": "assistant", "content": "", "tool_calls": "not a list"}},
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_order", "arguments": "not an object"}}],
            }
        },
    ],
)
def test_bad_server_responses_cannot_be_reported_as_success(response):
    task = make_task("refund", 1)
    with model_server([response]) as (endpoint, _):
        episode, record = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert episode.stop_reason == "error"
    assert "error" in record
    assert not verify(task, episode).passed


def test_response_size_limit_is_enforced():
    task = make_task("refund", 1)
    with model_server([(200, b" " * (MAX_RESPONSE + 1))]) as (endpoint, _):
        episode, record = run_model(task, model="scripted-http-test", endpoint=endpoint)
    assert episode.stop_reason == "error"
    assert "exceeded 4 MiB" in record["error"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/model",
        "ftp://localhost",
        "http://user:secret@localhost",
        "http://localhost/api/chat",
        "http://localhost?query=1",
        "http://localhost#fragment",
    ],
)
def test_endpoint_must_be_an_explicit_http_origin(endpoint):
    with pytest.raises(ValueError, match="endpoint"):
        run_model(make_task("refund", 1), model="test", endpoint=endpoint)


@pytest.mark.parametrize(
    "options",
    [
        {"max_steps": 0},
        {"max_steps": True},
        {"max_steps": 1.5},
        {"max_turns": 0},
        {"max_turns": True},
        {"max_turns": 2.5},
        {"seed": True},
        {"seed": -1},
        {"timeout": 0},
        {"deadline": -1},
        {"timeout": float("nan")},
        {"deadline": float("inf")},
        {"temperature": -1},
        {"temperature": float("nan")},
    ],
)
def test_invalid_budgets_are_configuration_errors(options):
    with pytest.raises(ValueError):
        run_model(make_task("refund", 1), model="test", **options)
