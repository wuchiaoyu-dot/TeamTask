# Extract TeamTask Candidates

Input may be a group message or meeting minutes. Extract concrete action items only.

Rules:

- Always include evidence snippets from the source text.
- For `meeting_minutes`, prefer action sections such as `未做完`, `待办`, `行动项`, `TODO`, and `下一步`.
- If initiator or assignee is unclear, lower confidence and add the missing field name to `missing_fields`.
- If a task has multiple assignees, create a parent task title and expand into one candidate per assignee with `parent_task_title`.
- Vague statements like "我们推进一下" without an explicit assignee must not be auto-distributed; mark `assignee` missing and keep confidence below the auto-confirm threshold.
- The LLM must not change task state. It only returns candidates.
