# TeamTask Agent Competition Demo Script

## Setup

Run the backend in safe local mock mode:

```powershell
copy .env.local.example .env
uvicorn app.main:app --reload
```

Optional smoke run:

```powershell
python demo/demo_smoke_test.py --base-url http://127.0.0.1:8000
```

## Demo Flow

1. Meeting task recognition
   - Submit a Feishu Minutes-style event or show `demo/sample_minutes.txt`.
   - TeamTask extracts action items and creates task candidates.

2. Initiator confirmation
   - Show the initiator card with task fields and related resources.
   - Click or simulate `initiator_confirm`.
   - The initiator personal Todo Projection is created.

3. Assignee acceptance
   - Show the assignee card.
   - Click or simulate `assignee_accept`.
   - The contract becomes `active` and the assignee projection is created.

4. Resource recommendation
   - Show high-confidence resources from explicit references.
   - Show low-confidence resources from keyword/semantic matches.

5. Group progress question
   - Send: `@TeamTask is u_assignee done with the competitive analysis?`
   - TeamTask matches the active contract.
   - It sends a confirmation card to the assignee instead of answering directly.

6. Assignee progress confirmation
   - Simulate `progress_mark_completed`.
   - TeamTask updates `completion_status` and the assignee projection.

7. Daily reconciliation
   - Trigger `/reconciliation/daily-run` or `/debug/reconciliation/run`.
   - Show a DDL/progress/resource diff card if personal projections diverge.

8. Initiator review
   - Simulate approving a deadline/title/description change.
   - TeamTask updates the contract and projections only after approval.

## Judge Talking Points

- The agent does not need super permissions.
- Every cross-user action is mediated by cards, grants, state transitions, and projections.
- Default mode is safe mock/dry-run.
- Real Feishu read/write can be enabled only for allowlisted trial users.
