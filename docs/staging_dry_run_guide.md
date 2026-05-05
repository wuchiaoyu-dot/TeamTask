# Staging Dry-Run Guide

This guide prepares TeamTask Agent for a real Feishu callback dry-run. It receives real Feishu events and card callbacks, but keeps external writes disabled.

## 1. Environment

Use `.env.staging.example` as the starting point:

```dotenv
ENV_PROFILE=staging_dry_run
FEISHU_MOCK=false
LARK_DRY_RUN=true
FEISHU_ENABLE_REAL_READ=false
TODO_BACKEND=bitable
MINUTES_BACKEND=lark_cli
RESOURCE_SEARCH_BACKEND=lark_cli
```

Optional real-read dry-run:

```dotenv
FEISHU_ENABLE_REAL_READ=true
MINUTES_DRY_RUN=true
RESOURCE_SEARCH_DRY_RUN=true
```

Required staging values:

```dotenv
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_VERIFICATION_TOKEN=...
FEISHU_CARD_VERIFICATION_TOKEN=...
FEISHU_BITABLE_APP_TOKEN=...
FEISHU_BITABLE_TABLE_ID=...
ALLOWED_USER_IDS=u_demo_initiator,u_demo_assignee
ALLOWED_CHAT_IDS=oc_demo_chat
PUBLIC_BASE_URL=https://your-public-url.example
```

## 2. Start Service

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 3. Public HTTPS

Use ngrok:

```powershell
ngrok http 8000
```

Or cloudflared:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Set the resulting HTTPS URL:

```dotenv
PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
```

## 4. Feishu Open Platform

Configure event subscription URL:

```text
{PUBLIC_BASE_URL}/feishu/events
```

Configure card callback URL:

```text
{PUBLIC_BASE_URL}/feishu/card-callback
```

Configure:

- Verification Token: use `FEISHU_VERIFICATION_TOKEN`
- Card Verification Token: use `FEISHU_CARD_VERIFICATION_TOKEN`
- Encrypt Key: can stay off for the first staging dry-run
- If encryption is enabled later, fill `FEISHU_ENCRYPT_KEY`, `FEISHU_CARD_ENCRYPT_KEY`, and enable `FEISHU_EVENT_ENCRYPTED=true`

## 5. Integration Checklist

Health:

```powershell
curl {PUBLIC_BASE_URL}/health
```

Readiness:

```powershell
curl {PUBLIC_BASE_URL}/readiness
```

System status:

```powershell
curl {PUBLIC_BASE_URL}/debug/system/status
```

If an external checklist says `POST /debug/system/status`, use the same path with the current backend's `GET` implementation.

Feishu checks:

- Invite the bot to an allowlisted group.
- Send `@TeamTask 张三这周五前整理竞品分析，参考上次评审文档`.
- Confirm that `/feishu/events` is hit in backend logs.
- Click an initiator card button.
- Confirm that `/feishu/card-callback` is hit in backend logs.
- Inspect `task_contracts`, `progress_queries`, `reconciliation_runs`, and `reconciliation_items` in SQLite.

## 6. Safety Expectations

- `LARK_DRY_RUN=true` means no real Bitable writes.
- `LARK_DRY_RUN=true` means no real Todo mutation.
- Non-allowlisted users are rejected in guarded real paths.
- Non-allowlisted chats are rejected in `production_trial` and guarded staging paths.
- Tokens, secrets, authorization headers, app tokens, document tokens, and minutes tokens must not appear in logs.
- `/debug/system/status` returns booleans and counts, not secret values.

## 7. Rollback

Switch back to safe local mode:

```dotenv
ENV_PROFILE=local_mock
FEISHU_MOCK=true
LARK_DRY_RUN=true
FEISHU_ENABLE_REAL_READ=false
TODO_BACKEND=mock
```
