# Sample Bitable Todo Projection Schema

Recommended fields for a demo table:

| Field | Type | Config key |
| --- | --- | --- |
| Owner | Text | `FEISHU_TODO_OWNER_FIELD` |
| contract_id | Text | `FEISHU_TODO_CONTRACT_ID_FIELD` |
| Task Title | Text | `FEISHU_TODO_TITLE_FIELD` |
| Task Description | Text | `FEISHU_TODO_DESCRIPTION_FIELD` |
| Initiator | Text | `FEISHU_TODO_INITIATOR_FIELD` |
| Assignee | Text | `FEISHU_TODO_ASSIGNEE_FIELD` |
| Status | Text | `FEISHU_TODO_STATUS_FIELD` |
| Deadline | Date | `FEISHU_TODO_DEADLINE_FIELD` |
| Source | Text | `FEISHU_TODO_SOURCE_FIELD` |
| Evidence | Long text | `FEISHU_TODO_EVIDENCE_FIELD` |
| Related Resources | Long text | `FEISHU_TODO_RESOURCE_FIELD` |
| Personal Role | Select/Text | `FEISHU_TODO_ROLE_FIELD` |
| progress_text | Long text | built-in patch field |
| completion_status | Text | built-in snapshot field |

Keep all fields as text/date for the first trial. Person and select fields can be introduced after the field mapper is verified with `LARK_DRY_RUN=true`.
