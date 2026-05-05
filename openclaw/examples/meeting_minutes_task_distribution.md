# Example: Meeting Minutes Task Distribution

User prompt:

```text
TeamTask, read this Feishu Minutes link and prepare task cards for the owners:
https://example.feishu.cn/minutes/mincn-demo-001
```

OpenClaw capability:

```json
{
  "capability": "parse_meeting_minutes_tasks",
  "input": {
    "minutes_token_or_url": "https://example.feishu.cn/minutes/mincn-demo-001"
  }
}
```

Backend path:

- `POST /feishu/events` for end-to-end event ingestion
- `POST /debug/minutes/extract-tasks` for no-write preview

Expected result:

- one or more task candidates
- initiator confirmation cards
- no Todo Projection until initiator confirms
