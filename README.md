# TeamTask Agent V1

FastAPI backend for a Feishu/Lark-oriented TeamTask Agent V1. The V1 goal is an active task distribution and progress reconciliation assistant: a team todo contract ledger, personal todo projections, confirmation cards, and a strict state machine.

The system intentionally avoids super-user behavior. Cross-person work is mediated by user authorization grants, task contracts, card confirmations, change proposals, and legal state transitions.

## Stack

- Python 3.11+
- FastAPI
- SQLAlchemy 2.0
- SQLite for local development
- Pydantic v2
- pytest
- python-dotenv
- Feishu/Lark client adapter with mock and lark-cli modes

## Project Layout

```text
app/
  main.py                   FastAPI routes
  db.py                     SQLAlchemy engine/session setup
  models.py                 users, grants, events, contracts, todos, proposals, card actions
  state_machine.py          only legal task state transitions live here
  clients/
    feishu_client.py        abstract FeishuClient interface, mock client, client factory
    lark_cli_client.py      local development adapter backed by lark-cli
  core/permissions.py       read/write/confirm/reconcile permission rules
  schemas/llm_task_schema.py
  services/event_router.py  rule-based intent + mock task extraction
  cards/builders.py         mock card JSON builders
tests/
  test_flows.py
  test_lark_cli_client.py
```

## Run Locally

```powershell
cd "C:\Users\ASUS\Documents\New project\teamtask-agent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

Open:

- API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## Feishu/Lark Modes

Default local mode is mock mode:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
```

When `FEISHU_MOCK=true`, the app never calls real Feishu/Lark. It prints message/card payloads through local logging and stores mock deliveries in memory for tests.

To use lark-cli locally:

```dotenv
FEISHU_MOCK=false
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
LARK_CLI_PATH=lark-cli
LARK_DRY_RUN=true
```

All lark-cli write operations default to `dry_run=True`. The adapter logs every command argument after redacting token/secret-like values. It supports identity switching with:

```python
client.as_user()
client.as_bot()
```

The CLI command uses `--as user` or `--as bot` under the hood.

## Install lark-cli

The official Feishu/Lark CLI is distributed through npm as `@larksuite/cli`.

```powershell
npm install -g @larksuite/cli
npx skills add larksuite/cli -y -g
lark-cli --help
```

If npm registry access is slow in mainland China, use a mirror:

```powershell
npm install -g @larksuite/cli --registry=https://registry.npmmirror.com
```

Official references:

- https://github.com/larksuite/cli
- https://feishu-cli.com/

## Login And Authorization

Initialize app credentials and log in:

```powershell
lark-cli config init
lark-cli auth login --recommend
lark-cli auth status
lark-cli doctor
```

For least-privilege testing, login by domain:

```powershell
lark-cli auth login --domain im,docs,drive,task,vc,contact
```

You can inspect exact permissions before applying them:

```powershell
lark-cli auth scopes
lark-cli schema im.messages.create
lark-cli schema task
```

## Dry-Run First

Keep `.env` in dry-run mode:

```dotenv
FEISHU_MOCK=false
LARK_DRY_RUN=true
```

Start the API and trigger a card flow. The lark-cli adapter will return the redacted command it would run, without sending a real message or writing a real task.

You can also test lark-cli directly:

```powershell
lark-cli im +messages-send --as bot --chat-id "oc_xxx" --text "TeamTask dry-run" --dry-run
```

Only set `LARK_DRY_RUN=false` after the command preview and Open Platform scopes are correct.

## Required Open Platform Scopes

Exact scope names vary by tenant and lark-cli/OpenAPI version. These capability areas usually need manual approval in the Feishu/Lark Open Platform console before real writes work:

- IM/Messenger: send direct messages, send group messages, send interactive cards, access target chats where the bot is installed.
- Task/Todo: create, update, query, and complete tasks or task-like projections.
- Docs/Drive/Wiki: search documents and read document metadata or snippets for resource discovery.
- VC/Minutes: read meeting records, minutes metadata, transcripts, AI summaries, and action items.
- Contact/User: resolve user IDs, names, and emails.
- Bot/User token usage: app access token for bot actions and user access token for user-authorized actions.

Use `lark-cli auth check <scope>` and `lark-cli schema <api>` to verify the exact scope set before disabling dry-run.

## Example Flow

Create a group message event and extract a task candidate:

```powershell
curl -X POST http://127.0.0.1:8000/events/group-message `
  -H "Content-Type: application/json" `
  -d "{\"source_id\":\"msg-001\",\"text\":\"Please ask u_assignee to finish TeamTask V1 integration by 2026-06-01.\",\"sender_user_id\":\"u_initiator\",\"participant_user_ids\":[\"u_initiator\",\"u_assignee\"],\"initiator_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"project_name\":\"TeamTask\"}"
```

Confirm as initiator:

```powershell
curl -X POST http://127.0.0.1:8000/cards/initiator/confirm `
  -H "Content-Type: application/json" `
  -d "{\"actor_user_id\":\"u_initiator\",\"contract_id\":1}"
```

Accept as assignee:

```powershell
curl -X POST http://127.0.0.1:8000/cards/assignee/accept `
  -H "Content-Type: application/json" `
  -d "{\"actor_user_id\":\"u_assignee\",\"contract_id\":1}"
```

Create both progress reconciliation grants for local testing:

```powershell
curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_initiator\",\"scope\":\"progress_reconcile\",\"subject_type\":\"user\",\"subject_id\":\"u_assignee\"}"

curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_assignee\",\"scope\":\"progress_reconcile\",\"subject_type\":\"user\",\"subject_id\":\"u_initiator\"}"
```

Query progress:

```powershell
curl -X POST http://127.0.0.1:8000/progress/query `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"query_text\":\"How is this task going?\"}"
```

Assignee confirms progress:

```powershell
curl -X POST http://127.0.0.1:8000/cards/progress/confirm `
  -H "Content-Type: application/json" `
  -d "{\"actor_user_id\":\"u_assignee\",\"contract_id\":1,\"progress_summary\":\"Integration is done; edge-case tests are in progress.\"}"
```

## Phase 3: End-To-End Mock Loop Test

Keep local mock defaults enabled:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
```

Start the API:

```powershell
python -m uvicorn app.main:app --reload
```

Simulate a Feishu group task assignment event:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"event_id\":\"evt-demo-001\",\"event_type\":\"group_message\",\"text\":\"Please assign u_assignee to finish the TeamTask E2E task by 2026-06-01.\",\"sender_user_id\":\"u_initiator\",\"participant_user_ids\":[\"u_initiator\",\"u_assignee\"],\"initiator_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"project_name\":\"TeamTask\"}"
```

The response includes `contract_id`. Use it in the card callback examples below.

Simulate initiator confirmation:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"action_key\":\"initiator_confirm\",\"contract_id\":1,\"recipient_user_id\":\"u_initiator\"}"
```

Simulate assignee acceptance:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"action_key\":\"assignee_accept\",\"contract_id\":1,\"recipient_user_id\":\"u_assignee\"}"
```

Simulate assignee deadline change proposal:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"action_key\":\"assignee_propose_change\",\"contract_id\":1,\"recipient_user_id\":\"u_assignee\",\"deadline\":\"2026-06-15\",\"reason\":\"Need review buffer\"}"
```

View the task contract state:

```powershell
curl http://127.0.0.1:8000/task-contracts/1
```

Idempotency checks:

- Reposting the same `/feishu/events` payload with the same `event_id` returns the existing contract.
- Reclicking the same confirm action returns the current contract state and does not create another personal todo projection.

## Phase 4: Real Feishu Callback Dry-Run

Phase 4 accepts real Feishu/Lark event subscription payloads and real interactive card callback payloads, but still keeps writes safe by default:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
FEISHU_EVENT_ENCRYPTED=false
FEISHU_VERIFICATION_TOKEN=your-event-token
FEISHU_CARD_VERIFICATION_TOKEN=your-card-token
FEISHU_ENCRYPT_KEY=
FEISHU_CARD_ENCRYPT_KEY=
PUBLIC_BASE_URL=https://your-public-url.example
```

Start the local API:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Expose it through an HTTPS tunnel. For example:

```powershell
ngrok http 8000
```

Or:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Set `PUBLIC_BASE_URL` to the public HTTPS URL, then configure these URLs in the Feishu/Lark Open Platform console:

- Event subscription URL: `{PUBLIC_BASE_URL}/feishu/events`
- Interactive card callback URL: `{PUBLIC_BASE_URL}/feishu/card-callback`

Configure the same Verification Token values in both the Open Platform console and `.env`.

For V1 dry-run, keep encryption disabled in the console or keep:

```dotenv
FEISHU_EVENT_ENCRYPTED=false
```

The code has explicit `decrypt_event_payload()` and `decrypt_card_payload()` placeholders for encrypted callbacks. Before production, implement and enable encrypted payload verification, keep token validation on, and avoid running with broad app permissions.

URL challenge test:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"type\":\"url_verification\",\"token\":\"your-event-token\",\"challenge\":\"challenge-code\"}"
```

Expected response:

```json
{"challenge":"challenge-code"}
```

Simulate a real `im.message.receive_v1` event payload:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"schema\":\"2.0\",\"header\":{\"event_id\":\"evt-real-001\",\"event_type\":\"im.message.receive_v1\",\"token\":\"your-event-token\"},\"event\":{\"sender\":{\"sender_id\":{\"user_id\":\"u_initiator\",\"open_id\":\"ou_initiator\"}},\"message\":{\"message_id\":\"om_demo\",\"chat_id\":\"oc_demo\",\"message_type\":\"text\",\"content\":\"{\\\"text\\\":\\\"Please assign u_assignee to finish the TeamTask real callback task by 2026-06-01.\\\"}\",\"mentions\":[{\"id\":{\"user_id\":\"u_assignee\",\"open_id\":\"ou_assignee\"}}]}}}"
```

Simulate a real interactive card callback for initiator confirmation:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"schema\":\"2.0\",\"header\":{\"event_id\":\"card-event-1\",\"event_type\":\"card.action.trigger\",\"token\":\"your-card-token\"},\"event\":{\"operator\":{\"user_id\":{\"user_id\":\"u_initiator\",\"open_id\":\"ou_initiator\"}},\"action\":{\"tag\":\"button\",\"value\":{\"action_key\":\"initiator_confirm\",\"contract_id\":1,\"recipient_user_id\":\"u_initiator\",\"source_event_id\":1},\"form_value\":{}}}}"
```

Simulate assignee acceptance:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"schema\":\"2.0\",\"header\":{\"event_id\":\"card-event-2\",\"event_type\":\"card.action.trigger\",\"token\":\"your-card-token\"},\"event\":{\"operator\":{\"user_id\":{\"user_id\":\"u_assignee\",\"open_id\":\"ou_assignee\"}},\"action\":{\"tag\":\"button\",\"value\":{\"action_key\":\"assignee_accept\",\"contract_id\":1,\"recipient_user_id\":\"u_assignee\",\"source_event_id\":1},\"form_value\":{}}}}"
```

Simulate assignee deadline change:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"schema\":\"2.0\",\"header\":{\"event_id\":\"card-event-3\",\"event_type\":\"card.action.trigger\",\"token\":\"your-card-token\"},\"event\":{\"operator\":{\"user_id\":{\"user_id\":\"u_assignee\",\"open_id\":\"ou_assignee\"}},\"action\":{\"tag\":\"button\",\"value\":{\"action_key\":\"assignee_propose_change\",\"contract_id\":1,\"recipient_user_id\":\"u_assignee\",\"source_event_id\":1},\"form_value\":{\"deadline\":\"2026-06-15\",\"reason\":\"Need review buffer\"}}}}"
```

Check state:

```powershell
curl http://127.0.0.1:8000/task-contracts/1
```

Scope reminders for real callback dry-run:

- IM/Messenger event subscription and message/card callback permissions.
- Bot installed in the target chat.
- Contact/user ID resolution if your tenant sends `open_id` but your test data expects `user_id`.
- Docs/Drive/Minutes permissions for meeting-minutes link expansion.
- Task/Todo scopes only after dry-run is validated; keep `LARK_DRY_RUN=true` until production approval.

## Phase 5: Bitable Todo Projection

Phase 5 upgrades `personal_todo_projections` from local-only mock records to an optional Feishu/Lark Bitable-backed Todo Projection store. The default remains safe:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
TODO_BACKEND=mock
```

To dry-run Bitable writes without creating real records:

```dotenv
FEISHU_MOCK=false
LARK_DRY_RUN=true
TODO_BACKEND=bitable
FEISHU_BITABLE_APP_TOKEN=base_xxx
FEISHU_BITABLE_TABLE_ID=tbl_xxx
FEISHU_BITABLE_VIEW_ID=
```

Create a Feishu Bitable as the TeamTask Todo library, then create a table with these recommended fields:

- `负责人`
- `contract_id`
- `任务标题`
- `任务描述`
- `发起者`
- `执行者`
- `状态`
- `截止时间`
- `来源`
- `证据片段`
- `相关资源`
- `个人角色`

All field names are configurable. Example:

```dotenv
FEISHU_TODO_OWNER_FIELD=负责人
FEISHU_TODO_CONTRACT_ID_FIELD=contract_id
FEISHU_TODO_TITLE_FIELD=任务标题
FEISHU_TODO_DESCRIPTION_FIELD=任务描述
FEISHU_TODO_INITIATOR_FIELD=发起者
FEISHU_TODO_ASSIGNEE_FIELD=执行者
FEISHU_TODO_STATUS_FIELD=状态
FEISHU_TODO_DEADLINE_FIELD=截止时间
FEISHU_TODO_SOURCE_FIELD=来源
FEISHU_TODO_EVIDENCE_FIELD=证据片段
FEISHU_TODO_RESOURCE_FIELD=相关资源
FEISHU_TODO_ROLE_FIELD=个人角色
```

Preview the exact Bitable fields without writing:

```powershell
curl -X POST http://127.0.0.1:8000/debug/bitable/dry-run-create `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1,\"owner_user_id\":\"u_initiator\"}"
```

After initiator confirmation or assignee acceptance, inspect local projection sync state:

```powershell
curl http://127.0.0.1:8000/task-contracts/1/projections
```

Response fields include:

- `todo_provider`: `mock` or `bitable`
- `external_record_id`: mock ID, dry-run ID, or real Bitable record ID
- `projection_status`
- `last_synced_at`

Important behavior:

- `initiator_confirm` creates or reuses the initiator projection and stores `external_record_id`.
- `assignee_accept` creates or reuses the assignee projection and stores `external_record_id`.
- Repeated confirmation clicks do not create duplicate local or external projections.
- `assignee_propose_change` does not update external Todo records.
- `change_proposal_approve` updates the contract first, then syncs existing initiator and assignee projections.

Real writes are still not recommended by default. Before setting `LARK_DRY_RUN=false`, verify:

- Bitable app token and table ID are correct.
- Bot/app has Bitable record create/update permission.
- Every configured field exists and has a compatible type.
- Date fields accept the generated timestamp format.
- No production table is used until dry-run JSON has been reviewed.

## Phase 6: Meeting Minutes Ingestion

Phase 6 lets TeamTask recognize a Feishu/Lark meeting-minutes link in a group message, read a mock or dry-run transcript, extract action items, and reuse the existing initiator-confirm -> assignee-confirm -> Todo Projection flow.

Safe defaults:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
MINUTES_BACKEND=mock
MINUTES_DRY_RUN=true
MINUTES_TEXT_MAX_CHARS=30000
MINUTES_TASK_SECTION_HINTS=已做完,未做完,待办,行动项,TODO,下一步
MINUTES_LINK_PATTERNS=
```

Parse a meeting-minutes link:

```powershell
curl -X POST http://127.0.0.1:8000/debug/minutes/parse-link `
  -H "Content-Type: application/json" `
  -d "{\"text\":\"Here are the meeting minutes: https://example.feishu.cn/minutes/min_mock_123\"}"
```

Dry-run task extraction without creating `task_contracts`:

```powershell
curl -X POST http://127.0.0.1:8000/debug/minutes/extract-tasks `
  -H "Content-Type: application/json" `
  -d "{\"minutes_token_or_url\":\"https://example.feishu.cn/minutes/min_mock_123\"}"
```

Simulate a real group message that forwards a minutes link:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"schema\":\"2.0\",\"header\":{\"event_id\":\"evt-minutes-001\",\"event_type\":\"im.message.receive_v1\"},\"event\":{\"sender\":{\"sender_id\":{\"user_id\":\"u_initiator\",\"open_id\":\"ou_initiator\"}},\"message\":{\"message_id\":\"om_minutes_001\",\"chat_id\":\"oc_minutes\",\"message_type\":\"text\",\"content\":\"{\\\"text\\\":\\\"Here are the meeting minutes: https://example.feishu.cn/minutes/min_mock_123\\\"}\",\"mentions\":[]}}}"
```

The response includes `contract_ids` when multiple action items are extracted. Multi-assignee action items are expanded into multiple candidates with `parent_task_title`.

Current V1 behavior:

- `FEISHU_MOCK=true` always uses `MockMinutesBackend`; no real lark-cli call is made.
- `MINUTES_BACKEND=lark_cli` keeps the real command boundary in `LarkCliMinutesBackend`.
- `MINUTES_DRY_RUN=true` returns mock content even for the lark-cli backend.
- Long transcripts are truncated by `MINUTES_TEXT_MAX_CHARS` before task extraction.
- Vague items such as "we should推进一下" without a clear assignee remain low-confidence and do not auto-create Todo projections.

Future production integration points:

- Replace `MockMinutesBackend` with real Feishu Minutes/OpenAPI transcript retrieval.
- Fill in the lark-cli command parser in `LarkCliMinutesBackend`.
- Confirm the required Minutes/VC scopes and user authorization model.
- Keep transcript truncation and action-section extraction in place so task extraction never receives unbounded meeting text.

## Phase 7: Resource Search and Confidence Ranking

Phase 7 adds resource recommendations after task candidates are created. TeamTask uses the task title, description, project name, resource keywords, mentioned resources, evidence snippets, and the source event to recommend Feishu docs, historical meeting notes, and project materials.

Safe defaults:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
RESOURCE_SEARCH_BACKEND=mock
RESOURCE_SEARCH_DRY_RUN=true
RESOURCE_SEARCH_TOP_K=5
RESOURCE_SEARCH_HIGH_CONFIDENCE_THRESHOLD=0.8
RESOURCE_SEARCH_LOW_CONFIDENCE_THRESHOLD=0.5
RESOURCE_SEARCH_ENABLE_FOR_INITIATOR=true
RESOURCE_SEARCH_ENABLE_FOR_ASSIGNEE=true
RESOURCE_SEARCH_MAX_QUERY_TERMS=8
RESOURCE_SEARCH_SOURCES=docs,minutes,base
```

Confidence buckets:

- `high_confidence`: explicit links in the meeting or group message, resources named in `mentioned_resources`, "reference XX doc" evidence, strong project/title matches, or resources from the current source context.
- `low_confidence`: semantic matches from `task_title`, `project_name`, and `resource_keywords`, related historical minutes, or recent/project-space materials with partial keyword matches.
- `ignore`: invalid results, unrelated generic docs, or scores below `RESOURCE_SEARCH_LOW_CONFIDENCE_THRESHOLD`.

Mock a task assignment with a referenced doc:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"event_id\":\"evt-resource-001\",\"event_type\":\"group_message\",\"text\":\"Please assign u_assignee to finish TeamTask resource review by 2026-06-01. See https://example.feishu.cn/docx/resource-alpha\",\"sender_user_id\":\"u_initiator\",\"participant_user_ids\":[\"u_initiator\",\"u_assignee\"],\"initiator_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"project_name\":\"TeamTask\"}"
```

Build search queries for a contract:

```powershell
curl -X POST http://127.0.0.1:8000/debug/resources/build-queries `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1}"
```

Run resource search without writing back:

```powershell
curl -X POST http://127.0.0.1:8000/debug/resources/search `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1,\"user_id\":\"u_initiator\",\"write_back\":false}"
```

Run resource search and save recommendations to `task_contracts.related_resources_json`:

```powershell
curl -X POST http://127.0.0.1:8000/debug/resources/search `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1,\"user_id\":\"u_initiator\",\"write_back\":true}"
```

Trigger the same flow from a card action:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"action_key\":\"initiator_request_resource_search\",\"contract_id\":1,\"recipient_user_id\":\"u_initiator\"}"
```

The initiator and assignee confirmation cards now include `related_resources.high_confidence` and `related_resources.low_confidence`, plus a resource-search button. In mock mode, no real Feishu Drive, Docs, Search, or lark-cli call is made.

Current V1 behavior:

- `MockResourceSearchBackend` returns deterministic local recommendations.
- Explicit `mentioned_resources` links become high-confidence resources.
- Evidence such as "reference LaunchPlan doc" becomes a high-confidence mock doc.
- Keyword-only matches become low-confidence resources.
- Search failures do not block the main confirmation flow; the contract is marked with `resource_search_status=failed`.
- `LarkCliResourceSearchBackend` keeps the future real command boundary, but `RESOURCE_SEARCH_DRY_RUN=true` or `LARK_DRY_RUN=true` returns mock results.

Future production integration points:

- Replace mock search with Feishu Drive / Docs / Search OpenAPI or lark-cli search commands.
- Add per-user document visibility checks before showing low-confidence recommendations.
- Preserve the high/low confidence split in cards so users can confirm explicit evidence separately from softer suggestions.

## Phase 8: Progress Query and Confirmation Cards

Phase 8 supports group-chat progress questions such as `@TeamTask Is u_assignee Competitive analysis done?`. TeamTask records a `progress_query`, matches an existing active task contract, sends a confirmation card to the assignee, and only generates a reply after the assignee confirms.

Why TeamTask does not answer directly:

- Progress belongs to the assignee's current working state.
- The system must not impersonate an assignee or infer completion from stale context.
- Deadline changes still follow the task contract ledger: delayed progress with a new DDL creates a `change_proposal` for initiator review instead of overwriting the contract.

Mock a progress question from a group message:

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"event_id\":\"evt-progress-001\",\"event_type\":\"group_message\",\"text\":\"@TeamTask Is u_assignee Competitive analysis done?\",\"sender_user_id\":\"u_initiator\",\"participant_user_ids\":[\"u_initiator\",\"u_assignee\"],\"initiator_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"project_name\":\"TeamTask\"}"
```

Debug task matching without sending a card:

```powershell
curl -X POST http://127.0.0.1:8000/debug/progress/query `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"query_text\":\"Is u_assignee Competitive analysis done?\"}"
```

Simulate assignee confirmation:

```powershell
curl -X POST http://127.0.0.1:8000/debug/progress/confirm `
  -H "Content-Type: application/json" `
  -d "{\"progress_query_id\":1,\"assignee_user_id\":\"u_assignee\",\"action_key\":\"progress_mark_in_progress\",\"progress_text\":\"Draft is 60 percent complete.\"}"
```

Simulate a delayed task with a proposed new deadline:

```powershell
curl -X POST http://127.0.0.1:8000/debug/progress/confirm `
  -H "Content-Type: application/json" `
  -d "{\"progress_query_id\":1,\"assignee_user_id\":\"u_assignee\",\"action_key\":\"progress_mark_delayed\",\"progress_text\":\"Need another review cycle.\",\"new_deadline\":\"2026-06-15\"}"
```

Progress card actions:

- `progress_mark_completed`: marks `completion_status=completed`, records progress text, and updates the assignee projection.
- `progress_mark_in_progress`: records progress text and updates the assignee projection.
- `progress_mark_blocked`: records the blocker and generates a reply payload for the requester/group.
- `progress_mark_delayed`: records delayed status; if a new deadline is provided, creates a `change_proposal`.
- `progress_no_such_task`: marks the query as `no_matching_task` and does not modify the task contract.
- `progress_select_task`: used when multiple high-scoring task candidates match.

Current safety behavior:

- `FEISHU_MOCK=true` only records mock card deliveries locally.
- `LARK_DRY_RUN=true` prevents real external Todo writes.
- `/progress/query` still enforces the earlier progress reconciliation grant checks.

## Phase 9: Reconciliation and Field Diff Review

Phase 9 adds the OpenClaw-style daily progress alignment loop. TeamTask still does not hold superuser access. It reconciles the initiator and assignee personal Todo Projections only when both sides have granted reconciliation permission.

Why no super permission:

- Each personal Todo view belongs to a user.
- Having `external_record_id` is not enough to read another user's Todo.
- Reconciliation requires active `user_auth_grants` from initiator to assignee and assignee to initiator.
- In `FEISHU_MOCK=true`, snapshots are local mock projections; in real mode, external reads must still pass the same permission gate.

Field ownership:

- Initiator-owned: `task_title`, `task_description`, `deadline`, `workload_level`, `project_name`
- Assignee-owned: `progress_text`, `completion_status`, `progress_updated_at`, `blocker_reason`
- Both-owned: `related_resources_json`, `mentioned_resources`, `evidence`
- System-owned: ids, provider metadata, timestamps, and other internal bookkeeping

Resolution rules:

- `deadline`, `title`, and `description` differences require initiator review.
- `progress_text` and `completion_status` are assignee-led and can sync to the initiator projection after assignee confirmation.
- Resource differences are merged with source markers instead of overwritten.
- Evidence is never auto-overwritten; it requires manual review.
- System fields cannot be changed through review cards.

Create both reconciliation grants for local testing:

```powershell
curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_initiator\",\"scope\":\"progress_reconcile\",\"subject_type\":\"user\",\"subject_id\":\"u_assignee\"}"

curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_assignee\",\"scope\":\"progress_reconcile\",\"subject_type\":\"user\",\"subject_id\":\"u_initiator\"}"
```

Run a single-task reconciliation:

```powershell
curl -X POST http://127.0.0.1:8000/debug/reconciliation/run `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"scope\":\"single_task\",\"contract_id\":1}"
```

Inspect a reconciliation run:

```powershell
curl http://127.0.0.1:8000/debug/reconciliation/runs/1
```

Apply a review action:

```powershell
curl -X POST http://127.0.0.1:8000/debug/reconciliation/apply-action `
  -H "Content-Type: application/json" `
  -d "{\"reconciliation_item_id\":1,\"action_key\":\"reconciliation_sync_progress\",\"actor_user_id\":\"u_assignee\",\"field_name\":\"progress_text\"}"
```

Simulate a daily reconciliation run:

```powershell
curl -X POST http://127.0.0.1:8000/reconciliation/daily-run `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\"}"
```

Useful response fields:

- `field_diffs_json`: per-field initiator value, assignee value, owner, policy, and suggested action
- `generated_card_json`: review card payload for the diff item
- `summary_card`: aggregate run summary with counts for consistent, diff, permission denied, and missing projections

Current V1 behavior:

- No scheduler is included yet; `/reconciliation/daily-run` is a manual trigger.
- Future scheduling can use cron, Feishu scheduled jobs, or an OpenClaw daily trigger.
- `LARK_DRY_RUN=true` keeps external Todo writes dry-run.
- `FEISHU_MOCK=true` never calls real Feishu/Lark.

## Phase 10: Real Bitable Integration

Phase 10 extends the Todo Projection backend so it can create, update, and read Feishu Bitable records through a `BitableClient` boundary. Safe defaults still remain mock/dry-run.

Recommended Bitable fields:

- Owner/user field: configured by `FEISHU_TODO_OWNER_FIELD`
- `contract_id`
- Title: configured by `FEISHU_TODO_TITLE_FIELD`
- Description: configured by `FEISHU_TODO_DESCRIPTION_FIELD`
- Initiator and assignee fields
- Status/completion field
- Deadline field
- Source, evidence, resources, and role fields
- Optional text field: `progress_text`

Minimum configuration:

```dotenv
FEISHU_MOCK=true
TODO_BACKEND=mock
LARK_DRY_RUN=true
FEISHU_BITABLE_APP_TOKEN=
FEISHU_BITABLE_TABLE_ID=
```

Dry-run Bitable preview:

```powershell
curl -X POST http://127.0.0.1:8000/debug/bitable/create-real `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1,\"owner_user_id\":\"u_initiator\",\"role\":\"initiator\"}"
```

When `FEISHU_MOCK=true` or `LARK_DRY_RUN=true`, the endpoint returns `external_write_allowed=false`, `would_write=true`, and the exact `fields` payload, but does not write to Feishu.

Read a Bitable record snapshot:

```powershell
curl -X POST http://127.0.0.1:8000/debug/bitable/get-record `
  -H "Content-Type: application/json" `
  -d "{\"owner_user_id\":\"u_initiator\",\"external_record_id\":\"recxxxx\"}"
```

Update a Bitable record:

```powershell
curl -X POST http://127.0.0.1:8000/debug/bitable/update-record `
  -H "Content-Type: application/json" `
  -d "{\"owner_user_id\":\"u_assignee\",\"external_record_id\":\"recxxxx\",\"patch\":{\"progress_text\":\"Draft is 70% complete\",\"completion_status\":\"in_progress\"}}"
```

Real write switch:

```dotenv
FEISHU_MOCK=false
TODO_BACKEND=bitable
LARK_DRY_RUN=false
FEISHU_BITABLE_APP_TOKEN=...
FEISHU_BITABLE_TABLE_ID=...
LARK_CLI_PATH=lark-cli
```

Real-write guardrails:

- External writes are allowed only when `FEISHU_MOCK=false`, `TODO_BACKEND=bitable`, `LARK_DRY_RUN=false`, required Bitable config is present, and the app is not running in the test harness.
- `validate_bitable_config()` reports missing `FEISHU_BITABLE_APP_TOKEN`, `FEISHU_BITABLE_TABLE_ID`, and missing auth path.
- `should_allow_external_write()` blocks mock, dry-run, non-Bitable, and test runtime writes.
- Token-like values, app secrets, app tokens, and authorization strings are redacted from lark-cli logs.
- `FeishuOpenApiBitableClient` is intentionally left as a clear TODO boundary for future HTTPS OpenAPI implementation.

Using real snapshots in reconciliation:

- `BitableTodoBackend.get_projection_snapshot()` reads a Bitable record through `BitableClient.get_record()`.
- `map_bitable_record_to_snapshot()` maps Bitable fields back to internal fields such as `title`, `description`, `deadline`, `progress_text`, `completion_status`, and `related_resources_json`.
- Reconciliation still checks both users' grants before reading and diffing projection snapshots.

## Phase 11: Real Minutes and Docs Search Integration

Phase 11 extends the Minutes and Resource Search backends so local dry-run can exercise the real-read boundary for Feishu Minutes, Docs, Drive, historical minutes, and Base search. The default remains safe:

```dotenv
FEISHU_MOCK=true
LARK_DRY_RUN=true
FEISHU_ENABLE_REAL_READ=false
MINUTES_BACKEND=mock
RESOURCE_SEARCH_BACKEND=mock
```

Real reads are blocked unless all of these are true:

- `FEISHU_MOCK=false`
- `LARK_DRY_RUN=false`
- `FEISHU_ENABLE_REAL_READ=true`
- `LARK_CLI_PATH` or Feishu OpenAPI credentials are configured
- the current user has the required `user_auth_grants`
- the app is not running in the test harness

Recommended dry-run configuration:

```dotenv
FEISHU_MOCK=false
LARK_DRY_RUN=true
FEISHU_ENABLE_REAL_READ=false
MINUTES_BACKEND=lark_cli
RESOURCE_SEARCH_BACKEND=lark_cli
MINUTES_DRY_RUN=true
RESOURCE_SEARCH_DRY_RUN=true
FEISHU_MINUTES_SCOPE_REQUIRED=minutes:read
FEISHU_DOCS_SCOPE_REQUIRED=docs:read
FEISHU_DRIVE_SCOPE_REQUIRED=drive:read
FEISHU_BASE_SCOPE_REQUIRED=base:read
```

Grant local debug scopes before testing read endpoints:

```powershell
curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_initiator\",\"scope\":\"minutes:read\"}"

curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_initiator\",\"scope\":\"docs:read\"}"
```

Check scopes:

```powershell
curl -X POST http://127.0.0.1:8000/debug/auth/scopes `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_initiator\",\"required_scopes\":[\"minutes:read\",\"docs:read\",\"drive:read\",\"base:read\"]}"
```

Dry-run a real Minutes read boundary:

```powershell
curl -X POST http://127.0.0.1:8000/debug/minutes/read-real `
  -H "Content-Type: application/json" `
  -d "{\"minutes_token_or_url\":\"https://example.feishu.cn/minutes/mincnxxxx\",\"user_id\":\"u_initiator\"}"
```

Dry-run resource search for an existing contract:

```powershell
curl -X POST http://127.0.0.1:8000/debug/resources/search-real `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1,\"user_id\":\"u_initiator\",\"write_back\":false}"
```

Failure and fallback behavior:

- If Minutes reading fails, TeamTask does not create an empty task and returns a readable error asking the user to paste meeting notes manually.
- If resource search fails, task confirmation continues; `resource_search_status=failed` and `resource_search_error` store the error summary.
- If scopes are missing, the debug endpoints return `missing_scopes` and do not attempt a real read.
- Logs redact token-like values, app secrets, authorization headers, minutes tokens, and document tokens.

Real-read replacement path:

- `LarkCliMinutesBackend` now has `parse_lark_cli_minutes_output()` and `normalize_minutes_segments()` as the stable adapter boundary.
- `LarkCliResourceSearchBackend` now has `parse_lark_cli_search_output()` and `normalize_resource_result()` as the stable adapter boundary.
- `Feishu OpenAPI` can replace lark-cli behind these boundaries without changing the TeamTask state machine or Todo Projection flow.

## Phase 12: Usable Demo and OpenClaw Packaging

Phase 12 packages the current backend for deployment, OpenClaw entry, Feishu callback dry-run, and competition demos. It does not add a new business workflow; it makes the existing task distribution, progress query, resource search, Todo Projection, and reconciliation flows easier to configure and show.

Current capabilities:

- Feishu event ingestion for group messages and meeting minutes.
- Initiator and assignee confirmation cards.
- Task status machine and idempotent card actions.
- Mock or Bitable-backed Todo Projections.
- Mock or lark-cli-backed Minutes reading and resource search boundaries.
- Progress query with assignee confirmation.
- Reconciliation with field ownership and review cards.
- OpenClaw wrapper manifest and demo prompts.

Runtime profiles:

| Profile | Purpose | Key defaults |
| --- | --- | --- |
| `local_mock` | local development and judge demo | `FEISHU_MOCK=true`, `LARK_DRY_RUN=true`, `FEISHU_ENABLE_REAL_READ=false`, mock backends |
| `staging_dry_run` | real Feishu callback wiring without writes | `FEISHU_MOCK=false`, `LARK_DRY_RUN=true`, `TODO_BACKEND=bitable` |
| `production_trial` | allowlisted small trial | `FEISHU_MOCK=false`, `LARK_DRY_RUN=false`, `FEISHU_ENABLE_REAL_READ=true`, `TODO_BACKEND=bitable` |

Example env files:

- `.env.local.example`
- `.env.staging.example`
- `.env.production.example`

Health and readiness:

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/readiness
curl http://127.0.0.1:8000/debug/system/status
```

`/debug/system/status` reports configuration booleans and guard status only; it does not return secrets, tokens, app secrets, or app tokens.

Allowlist trial controls:

```dotenv
ALLOWED_USER_IDS=u_demo_initiator,u_demo_assignee
ALLOWED_CHAT_IDS=oc_demo_chat
ENABLE_REAL_WRITE_FOR_ALLOWED_USERS_ONLY=true
ENABLE_REAL_READ_FOR_ALLOWED_USERS_ONLY=true
```

In `production_trial`, non-allowlisted users or chats cannot trigger real read/write paths. `staging_dry_run` can receive callbacks and return preview payloads, but keeps external writes disabled.

Run the demo smoke test:

```powershell
uvicorn app.main:app --reload
python demo/demo_smoke_test.py --base-url http://127.0.0.1:8000
```

Demo assets:

- `demo/sample_minutes.txt`
- `demo/sample_group_messages.json`
- `demo/sample_users.json`
- `demo/sample_bitable_schema.md`
- `demo/demo_script.md`
- `demo/demo_smoke_test.py`

OpenClaw packaging:

- `openclaw/skill_manifest.json` defines five capabilities: meeting minutes parsing, group assignment, progress query, reconciliation, and related resource search.
- `openclaw/README.md` explains that OpenClaw is the natural-language entrypoint while FastAPI remains the state and permission execution layer.
- `openclaw/examples/` contains prompt examples for meeting task distribution, group progress queries, and daily reconciliation.

Deployment notes:

- See `docs/deployment.md` for local run, ngrok/cloudflared callback setup, staging dry-run, production trial, and rollback.
- See `docs/feishu_setup_checklist.md` for the Feishu app, bot, event, card, scope, Bitable, and allowlist checklist.

Recommended competition demo flow:

1. Show meeting minutes task recognition.
2. Confirm as initiator.
3. Accept as assignee.
4. Show high/low confidence resources.
5. Ask progress in a group-style message.
6. Confirm progress as assignee.
7. Run reconciliation.
8. Show field-diff review and approval.

This version is ready for mock demos and allowlisted trials. It is still not recommended for full-company rollout until real Feishu scopes, Bitable field mapping, allowlists, and callback security have been verified in `staging_dry_run`.

## Tests

```powershell
python -m pytest
```

Current coverage verifies:

- Initiator confirmation does not write the assignee's Todo.
- Assignee acceptance creates the assignee's own Todo.
- Assignee deadline/title/description changes create `change_proposals` instead of overwriting the contract.
- Progress reconciliation requires both sides' authorization grants.
- Low-confidence mock LLM candidates do not automatically write Todo projections.
- lark-cli write operations are dry-run by default.
- lark-cli actor switching uses `--as user` / `--as bot`.
- lark-cli command logging redacts token-like values.
- Resource search separates explicit/high-confidence references from low-confidence semantic matches.
- Real-read guards block mock, dry-run, disabled, test-runtime, and missing-scope reads.
- Phase 12 packaging verifies profiles, allowlists, health/readiness, OpenClaw manifest, and demo smoke API flow.
