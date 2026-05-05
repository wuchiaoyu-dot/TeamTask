# TeamTask Agent OpenClaw Wrapper

This folder is a packaging layer, not a separate runtime. OpenClaw can act as the natural-language entrypoint, while the FastAPI backend remains the authority for task state, permission checks, Todo Projection writes, card callbacks, and reconciliation.

## Architecture

- OpenClaw receives user intent and chooses a capability from `skill_manifest.json`.
- OpenClaw calls the TeamTask FastAPI backend with normalized inputs.
- TeamTask creates contracts, cards, progress queries, or reconciliation runs.
- Feishu/Lark delivery remains controlled by `FEISHU_MOCK`, `LARK_DRY_RUN`, real-read guards, real-write guards, and allowlists.

## Capabilities

- `parse_meeting_minutes_tasks`: meeting link or pasted notes to task candidates.
- `assign_task_from_group_message`: group message to initiator confirmation card.
- `query_task_progress`: group progress question to assignee confirmation card.
- `run_task_reconciliation`: Todo Projection snapshot diff to review cards.
- `search_related_resources`: high/low confidence resource recommendation.

## Safety Contract

TeamTask does not expose a super-permission API. Every real read or write path is gated by environment profile, dry-run flags, user scopes, and allowlists. OpenClaw should never synthesize card `action_key` values; it should use backend-generated cards and callbacks.

## Local Demo

Use `ENV_PROFILE=local_mock` for judges or development demos. The backend returns mock cards and mock resources without reading or writing Feishu.

```powershell
uvicorn app.main:app --reload
python demo/demo_smoke_test.py --base-url http://127.0.0.1:8000
```
