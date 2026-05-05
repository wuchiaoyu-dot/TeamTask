from __future__ import annotations

import argparse
import json
import time
from typing import Any

import httpx


def run_smoke_test(base_url: str) -> dict[str, Any]:
    event_suffix = int(time.time())
    summary: dict[str, Any] = {"base_url": base_url, "steps": []}

    with httpx.Client(base_url=base_url, timeout=20.0) as client:
        health = _get(client, "/health")
        summary["steps"].append({"step": "health", "result": health})

        for user_id in ("u_initiator", "u_assignee"):
            for scope in ("minutes:read", "docs:read", "drive:read", "base:read", "progress_reconcile"):
                _post(client, "/dev/auth-grants", {"user_id": user_id, "scope": scope})

        event = _post(
            client,
            "/feishu/events",
            {
                "event_id": f"demo-minutes-{event_suffix}",
                "event_type": "meeting_minutes",
                "chat_id": "oc_demo_chat",
                "text": (
                    "Action items: Please assign u_assignee to finish the competitive analysis "
                    "brief by 2026-06-01. Refer to LaunchPlan document."
                ),
                "sender_user_id": "u_initiator",
                "participant_user_ids": ["u_initiator", "u_assignee"],
                "initiator_user_id": "u_initiator",
                "assignee_user_id": "u_assignee",
                "project_name": "TeamTask Demo",
            },
        )
        contract_id = event["contract_id"]
        summary["steps"].append({"step": "meeting_event", "contract_id": contract_id, "status": event["contract_status"]})

        initiator = _post(
            client,
            "/feishu/card-callback",
            {"action_key": "initiator_confirm", "contract_id": contract_id, "recipient_user_id": "u_initiator"},
        )
        summary["steps"].append({"step": "initiator_confirm", "status": initiator["contract_status"]})

        assignee = _post(
            client,
            "/feishu/card-callback",
            {"action_key": "assignee_accept", "contract_id": contract_id, "recipient_user_id": "u_assignee"},
        )
        summary["steps"].append({"step": "assignee_accept", "status": assignee["contract_status"]})

        resources = _post(
            client,
            "/debug/resources/search",
            {"contract_id": contract_id, "user_id": "u_initiator", "write_back": True},
        )
        summary["steps"].append(
            {
                "step": "resource_search",
                "high": len(resources["high_confidence"]),
                "low": len(resources["low_confidence"]),
            }
        )

        progress_query = _post(
            client,
            "/debug/progress/query",
            {
                "requester_user_id": "u_initiator",
                "assignee_user_id": "u_assignee",
                "query_text": "Is u_assignee done with the competitive analysis?",
            },
        )
        progress_query_id = progress_query["progress_query_id"]
        summary["steps"].append({"step": "progress_query", "progress_query_id": progress_query_id})

        progress_confirm = _post(
            client,
            "/debug/progress/confirm",
            {
                "progress_query_id": progress_query_id,
                "assignee_user_id": "u_assignee",
                "action_key": "progress_mark_completed",
                "progress_text": "Completed for the demo.",
            },
        )
        summary["steps"].append(
            {
                "step": "progress_confirm",
                "completion_status": progress_confirm["updated_task_contract"]["completion_status"],
            }
        )

        reconciliation = _post(
            client,
            "/debug/reconciliation/run",
            {"requester_user_id": "u_initiator", "scope": "single_task", "contract_id": contract_id},
        )
        summary["steps"].append(
            {
                "step": "reconciliation",
                "run_id": reconciliation["run_id"],
                "summary": reconciliation["summary"],
            }
        )

    return summary


def _get(client: httpx.Client, path: str) -> dict[str, Any]:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def _post(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TeamTask Agent local demo smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run_smoke_test(args.base_url), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
