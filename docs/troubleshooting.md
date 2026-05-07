# Troubleshooting

## 1. 飞书事件收不到

- 确认本地服务已启动：`curl http://127.0.0.1:8000/health`
- 确认公网 HTTPS 隧道可访问。
- 确认飞书事件订阅 URL 是 `{PUBLIC_BASE_URL}/feishu/events`。
- 查看 `/readiness` 里的 `feishu_callback_config_ok` 和 warnings。

## 2. 卡片点击没有回调

- 确认卡片回调 URL 是 `{PUBLIC_BASE_URL}/feishu/card-callback`。
- 确认卡片 payload 中包含 `action_key`、`contract_id`、`recipient_user_id`。
- 确认 `action_key` 来自 `cards/builders.py`，不要让 LLM 生成 action key。

## 3. challenge 校验失败

- 确认飞书 URL challenge 请求没有被代理改写。
- 确认 `FEISHU_VERIFICATION_TOKEN` 与飞书开放平台配置一致。
- V1 联调建议先保持 `FEISHU_EVENT_ENCRYPTED=false`。

## 4. verification token 错误

- 事件订阅使用 `FEISHU_VERIFICATION_TOKEN`。
- 卡片回调使用 `FEISHU_CARD_VERIFICATION_TOKEN`。
- 两个 token 不要混用。

## 5. Bitable 写入失败

- 确认 `TODO_BACKEND=bitable`。
- 确认 `FEISHU_BITABLE_APP_TOKEN` 和 `FEISHU_BITABLE_TABLE_ID` 已配置。
- 先用 `BITABLE_DRY_RUN=true` 和 `TODO_PROJECTION_DRY_RUN=true` 调 `/debug/bitable/create-real` 查看 fields。
- 确认多维表格字段名和 `.env` 字段映射一致。

## 6. scope 不足

- 调用 `/debug/auth/scopes` 查看缺少哪些 scope。
- 会议妙记读取通常需要 `minutes:read`。
- 文档检索通常需要 `docs:read`、`drive:read`。
- Base 检索或 Bitable 读取需要对应 Base/Bitable scope。

## 7. 白名单拦截

- `production_trial` 必须配置 `ALLOWED_USER_IDS`。
- 群聊入口建议配置 `ALLOWED_CHAT_IDS`。
- 非白名单用户会收到 403。
- 查看 `/debug/system/status` 的 allowlist count，但该接口不会泄露具体用户列表。

## 8. dry-run 导致没有真实写入或发卡片

- 这是安全默认行为。
- 卡片发送由 `LARK_CLI_DRY_RUN` / `FEISHU_SEND_DRY_RUN` 控制。
- Bitable/Todo 写入由 `BITABLE_DRY_RUN` / `TODO_PROJECTION_DRY_RUN` 控制。
- 资源检索由 `RESOURCE_SEARCH_REAL_READ` / `RESOURCE_SEARCH_DRY_RUN` 控制。

## 9. demo smoke test 失败

- 直接运行：`python demo/demo_smoke_test.py`
- 默认会使用 in-process local mock，不需要启动 uvicorn。
- 如果传了 `--base-url`，请确认该地址确实是 TeamTask 后端。
- 如果看到 404，通常是端口 8000 被其他服务占用。

## 10. pytest 失败如何定位

- 先跑全量：`python -m pytest`
- 单独跑失败文件：`python -m pytest tests/test_xxx.py -q`
- 如果和环境变量有关，检查测试是否残留 `FEISHU_MOCK`、`LARK_DRY_RUN`、`ENV_PROFILE`。
- 如果和数据库有关，确认测试使用内存 SQLite fixture，不要复用本地 `teamtask_agent.db`。
