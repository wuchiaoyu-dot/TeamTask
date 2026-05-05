# Example: Reconciliation Daily Run

User prompt:

```text
TeamTask, reconcile today's TeamTask project todos between u_initiator and u_assignee.
```

OpenClaw capability:

```json
{
  "capability": "run_task_reconciliation",
  "input": {
    "project_name": "TeamTask",
    "assignee_user_id": "u_assignee"
  }
}
```

Backend path:

- `POST /reconciliation/daily-run`
- `POST /debug/reconciliation/run` for a one-off preview

Expected result:

- reconciliation run summary
- diff review cards for deadline/title/description/progress/resource differences
- permission-denied items when either side has not granted access
