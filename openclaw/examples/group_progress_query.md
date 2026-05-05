# Example: Group Progress Query

User prompt:

```text
@TeamTask Is u_assignee done with the competitive analysis?
```

OpenClaw capability:

```json
{
  "capability": "query_task_progress",
  "input": {
    "requester_user_id": "u_initiator",
    "assignee_user_id": "u_assignee",
    "query_text": "Is u_assignee done with the competitive analysis?"
  }
}
```

Backend path:

- `POST /debug/progress/query`
- `POST /feishu/events` for real group messages

Expected result:

- matched task contract if there is a strong keyword match
- assignee progress confirmation card
- no direct answer on behalf of the assignee
