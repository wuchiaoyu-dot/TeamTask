# Submission Brief

## 1. Project Name

TeamTask Agent：面向飞书团队协作的任务识别与进度对账助手

## 2. One-Line Introduction

从会议纪要、群聊消息和文档上下文中识别任务，经由发起者与执行者双向确认，生成可追踪的 Task Contract Ledger，并在不突破个人授权边界的前提下完成 Todo 同步、进度查询和字段对账。

## 3. Problem

- 会议后任务散落，行动项没有统一落地。
- 群聊任务难追踪，责任人和截止时间容易丢失。
- 发起者和执行者 Todo 不一致。
- 任务上下文和参考资料缺失。
- 进度查询容易越权或误代表他人回答。

## 4. Core Solution

- Task Contract Ledger: 将跨人任务变成可审计合同账本。
- Personal Todo Projection: 为发起者和执行者分别生成个人 Todo 视图。
- 双向确认卡片: 发起者确认后才分发，执行者接受后才激活。
- 高/低置信度资源推荐: 明确引用和语义搜索分层展示。
- Progress Query: 群聊问进度时先问执行者确认。
- Reconciliation: 对账双方 Todo Projection，按字段归属生成审核卡片。
- Change Proposal: 执行者修改 deadline/title/description 时不直接覆盖，而是进入发起者审核。

## 5. Safety And Permission Design

- 不保存超级权限。
- 只按用户授权读取。
- 写入 Todo 必须本人确认。
- 执行者不能直接覆盖发起者字段。
- 对账需要双方授权。
- 默认 dry-run 和白名单。
- `production_trial` 只允许 allowlisted users 和 allowlisted chats。

## 6. Technical Architecture

- FastAPI backend
- Feishu Event Adapter
- Card Callback
- Lark CLI / Bitable Client
- Minutes Backend
- Resource Search Backend
- Todo Backend
- Reconciliation Service
- OpenClaw packaging manifest

## 7. Current Completion

- `python -m pytest`: 119 passed at phase 13 checkpoint.
- `python demo/demo_smoke_test.py`: local_mock smoke test completes 10 steps.
- `staging_dry_run` can receive real Feishu callbacks without real writes.
- `production_trial` supports allowlisted trial users.

## 8. Demo Storyline

1. 会议任务识别。
2. 发起者确认。
3. 执行者接受。
4. 资源推荐。
5. 群聊问进度。
6. 执行者确认进度。
7. 对账发现差异。
8. 发起者审核变更。

## 9. Roadmap

- 发布真实 OpenClaw Skill。
- 接入更完整的飞书权限授权流程。
- 引入真实文档向量检索。
- 增加团队级任务看板。
- 构建任务质量评测集。
