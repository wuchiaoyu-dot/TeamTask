# API Demo Collection

All examples assume local mock mode:

```powershell
uvicorn app.main:app --reload
```

## 1. Health

```powershell
curl http://127.0.0.1:8000/health
```

## 2. Readiness

```powershell
curl http://127.0.0.1:8000/readiness
```

## 3. Simulate Meeting Minutes Event

Optional LLM semantic extraction for demos:

```powershell
$env:TASK_EXTRACTOR_BACKEND="llm"
$env:LLM_TASK_API_BASE="https://api.openai.com/v1"
$env:LLM_TASK_API_KEY="your_key"
$env:LLM_TASK_MODEL="your_model"
```

For Ark models that reject `response_format`, add:

```powershell
$env:LLM_TASK_RESPONSE_FORMAT="none"
```

Use `TASK_EXTRACTOR_BACKEND=auto` if you want the same demo to fall back to rule extraction when the model is not configured.

```powershell
curl -X POST http://127.0.0.1:8000/feishu/events `
  -H "Content-Type: application/json" `
  -d "{\"event_id\":\"demo-minutes-001\",\"event_type\":\"meeting_minutes\",\"chat_id\":\"oc_demo_chat\",\"text\":\"Action items: Please assign u_assignee to finish the competitive analysis brief by 2026-06-01. Refer to LaunchPlan document.\",\"sender_user_id\":\"u_initiator\",\"participant_user_ids\":[\"u_initiator\",\"u_assignee\"],\"initiator_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"project_name\":\"TeamTask Demo\"}"
```

## 4. Initiator Confirm

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"action_key\":\"initiator_confirm\",\"contract_id\":1,\"recipient_user_id\":\"u_initiator\"}"
```

## 5. Assignee Accept

```powershell
curl -X POST http://127.0.0.1:8000/feishu/card-callback `
  -H "Content-Type: application/json" `
  -d "{\"action_key\":\"assignee_accept\",\"contract_id\":1,\"recipient_user_id\":\"u_assignee\"}"
```

## 6. Resource Search

```powershell
curl -X POST http://127.0.0.1:8000/debug/resources/search `
  -H "Content-Type: application/json" `
  -d "{\"contract_id\":1,\"user_id\":\"u_initiator\",\"write_back\":true}"
```

## 7. Progress Query

```powershell
curl -X POST http://127.0.0.1:8000/debug/progress/query `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"assignee_user_id\":\"u_assignee\",\"query_text\":\"Is u_assignee done with the competitive analysis?\"}"
```

## 8. Progress Confirm

```powershell
curl -X POST http://127.0.0.1:8000/debug/progress/confirm `
  -H "Content-Type: application/json" `
  -d "{\"progress_query_id\":1,\"assignee_user_id\":\"u_assignee\",\"action_key\":\"progress_mark_completed\",\"progress_text\":\"Completed for the demo.\"}"
```

## 9. Reconciliation Run

Create reconciliation grants first:

```powershell
curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_initiator\",\"scope\":\"progress_reconcile\",\"subject_type\":\"user\",\"subject_id\":\"u_assignee\"}"

curl -X POST http://127.0.0.1:8000/dev/auth-grants `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"u_assignee\",\"scope\":\"progress_reconcile\",\"subject_type\":\"user\",\"subject_id\":\"u_initiator\"}"
```

Run reconciliation:

```powershell
curl -X POST http://127.0.0.1:8000/debug/reconciliation/run `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"scope\":\"single_task\",\"contract_id\":1}"
```

## 10. Reconciliation Apply Action

```powershell
curl -X POST http://127.0.0.1:8000/debug/reconciliation/apply-action `
  -H "Content-Type: application/json" `
  -d "{\"reconciliation_item_id\":1,\"action_key\":\"reconciliation_approve_change\",\"actor_user_id\":\"u_initiator\",\"field_name\":\"deadline\",\"resolution_value\":\"2026-06-08\"}"
```

## One-Command Smoke Test

```powershell
python demo/demo_smoke_test.py
```
