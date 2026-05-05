# Staging Manual Test

Use this script for a real Feishu staging dry-run. Keep `LARK_DRY_RUN=true` unless the team explicitly approves real external writes.

## Test 1: Group Task Assignment

In the Feishu group, send:

```text
@TeamTask 张三这周五前整理竞品分析，参考上次评审文档
```

Expected:

- Backend receives `/feishu/events`.
- The event intent is `assign_task`.
- TeamTask creates a `task_contract`.
- Initiator receives a confirmation card.

Click initiator confirm.

Expected:

- Initiator Todo Projection is created locally or dry-run external record id is returned.
- Assignee receives a confirmation card.

Assignee clicks accept.

Expected:

- Task status becomes `active`.
- Assignee Todo Projection is created.

## Test 2: Meeting Minutes Link

In the group, send a mock or real Feishu Minutes link:

```text
@TeamTask 请从这个会议纪要里整理行动项：https://example.feishu.cn/minutes/mincn-demo-001
```

Expected:

- System recognizes `meeting_minutes`.
- In dry-run, the backend returns `would_read=true` or mock transcript.
- Candidate tasks are generated.
- No real external read occurs unless real-read is explicitly enabled and authorized.

## Test 3: Resource Recommendation

Click `启动相关资源检索` on the initiator or assignee card.

Expected:

- Card contains `high_confidence` and `low_confidence` resources.
- Explicit links or referenced docs appear as high confidence.
- Keyword-only results appear as low confidence.
- In dry-run, no unauthorized private document is accessed.

## Test 4: Progress Query

In the group, send:

```text
@TeamTask 张三那个竞品分析做完了吗？
```

Expected:

- Backend recognizes `ask_progress`.
- It does not create a new task contract.
- It sends a progress confirmation card to 张三.

张三 clicks one of:

- 已完成
- 进行中
- 延期
- 阻塞

Expected:

- The backend records `progress_query`.
- It updates `completion_status` or creates a Change Proposal for deadline changes.
- It generates a reply summary for the group or requester.

## Test 5: Reconciliation

Trigger reconciliation:

```powershell
curl -X POST {PUBLIC_BASE_URL}/debug/reconciliation/run `
  -H "Content-Type: application/json" `
  -d "{\"requester_user_id\":\"u_initiator\",\"scope\":\"single_task\",\"contract_id\":1}"
```

Expected:

- If both sides have grants, a reconciliation run is created.
- Field differences produce review cards.
- DDL differences require initiator review.
- Initiator approves the DDL diff.
- Final summary reports consistent, has_diff, permission_denied, or missing projection counts.
