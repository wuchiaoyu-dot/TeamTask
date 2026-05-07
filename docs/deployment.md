# Deployment Guide

TeamTask Agent is safest when deployed in layers: `local_mock`, then `staging_dry_run`, then `production_trial`.

## 1. Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.local.example .env
uvicorn app.main:app --reload
```

Check:

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/readiness
```

## 2. Public HTTPS for Feishu Callbacks

Use any trusted tunnel. Examples:

```powershell
ngrok http 8000
```

or:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Set:

```dotenv
PUBLIC_BASE_URL=https://your-public-domain.example
```

## 3. Feishu Event Subscription URL

Configure:

```text
{PUBLIC_BASE_URL}/feishu/events
```

Keep `FEISHU_EVENT_ENCRYPTED=false` for the first V1 dry-run callback test. Turn encryption on before broader production use.

## 4. Feishu Card Callback URL

Configure:

```text
{PUBLIC_BASE_URL}/feishu/card-callback
```

Set both verification tokens:

```dotenv
FEISHU_VERIFICATION_TOKEN=...
FEISHU_CARD_VERIFICATION_TOKEN=...
```

## 5. Bitable Fields

Create a Feishu Bitable table using `demo/sample_bitable_schema.md`. Fill:

```dotenv
FEISHU_BITABLE_APP_TOKEN=...
FEISHU_BITABLE_TABLE_ID=...
```

Keep `BITABLE_DRY_RUN=true` and `TODO_PROJECTION_DRY_RUN=true` until `/debug/bitable/create-real` returns the fields you expect.

## 6. Staging Dry-Run

```powershell
copy .env.staging.example .env
```

Expected behavior:

- receives real Feishu events and card callbacks
- uses real callback verification
- may dry-run read/search boundaries
- does not write real Todo/Bitable records

## 7. Production Trial

```powershell
copy .env.production.example .env
```

Required:

- `ALLOWED_USER_IDS` contains every trial user
- `ALLOWED_CHAT_IDS` contains every trial chat
- `FEISHU_MOCK=false`
- `LARK_DRY_RUN=false`
- `LARK_CLI_DRY_RUN=false`
- `BITABLE_DRY_RUN=false`
- `TODO_PROJECTION_DRY_RUN=false`
- `FEISHU_ENABLE_REAL_READ=true`
- `TODO_BACKEND=bitable`

Run `/readiness` before inviting users.

## 8. Rollback

Immediate safe rollback:

```dotenv
ENV_PROFILE=local_mock
FEISHU_MOCK=true
LARK_DRY_RUN=true
LARK_CLI_DRY_RUN=true
BITABLE_DRY_RUN=true
TODO_PROJECTION_DRY_RUN=true
FEISHU_ENABLE_REAL_READ=false
TODO_BACKEND=mock
```

This preserves local state while blocking all external reads and writes.
