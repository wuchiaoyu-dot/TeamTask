# TeamTask Agent 比赛演示稿

## 1. 一句话定位

TeamTask Agent 是一个面向飞书和 OpenClaw 场景的团队任务合同账本助手：它从会议纪要和群聊里识别任务，先让发起者和执行者确认，再把任务投影到个人 Todo，并在之后做进度查询和字段差异对账。

## 2. 企业协作痛点

很多团队的问题不是没有 Todo 工具，而是任务在跨人流转时缺少“谁确认过什么”的可追溯账本。会议里说了任务，群聊里又补了资源，执行者私下改了 DDL，发起者看到的是另一套信息，最后进度对齐靠人肉追问。

## 3. 为什么不是普通 Todo

普通 Todo 只记录一条个人任务。TeamTask 的核心是 Task Contract Ledger：先形成 task_contract，再生成发起者和执行者各自的 Todo Projection。两个人可以有自己的视图，但关键字段的变更必须经过状态机、确认卡片和 Change Proposal。

## 4. Demo 人物

- 王总：任务发起者，负责确认任务目标、DDL 和验收口径。
- 张三：任务执行者，负责接受任务、补充进度、反馈阻塞。
- TeamTask Agent：任务识别与进度对账助手，负责抽取、推送、对账和生成审核卡片。

## 5. Demo 主线

1. 会议纪要产生任务
   - 王总会后转发会议妙记。
   - TeamTask 识别“张三完成竞品分析，截止 6 月 1 日”。

2. 发起者确认
   - 系统不直接写张三 Todo。
   - 先给王总发发起者确认卡片。

3. 执行者确认
   - 王总确认后，系统创建王总的 Todo Projection。
   - 再给张三发执行者确认卡片。

4. 推荐参考资源
   - 系统根据任务标题、项目名、证据片段和资源关键词检索资料。
   - 高置信度资源来自明确提到的文档或链接。
   - 低置信度资源来自关键词或语义相似内容。

5. 群聊查询进度
   - 王总在群里问：“张三那个竞品分析做完了吗？”
   - TeamTask 匹配任务，但不会替张三直接回答。

6. 执行者确认进度
   - 系统给张三发送进度确认卡片。
   - 张三选择已完成、进行中、延期、阻塞或没有这个任务。

7. 对账发现 DDL 不一致
   - 每日对账读取双方已授权的 Todo Projection。
   - 如果张三侧 Todo 的 DDL 和王总侧不一致，生成字段差异审核卡片。

8. 发起者审核变更
   - DDL、标题、描述属于发起者主控字段。
   - 王总审核通过后，系统才同步 task_contract 和双方 Projection。

## 6. 安全亮点

- 不保存超级权限：真实读取和写入都受 user_auth_grants、白名单、dry-run 和环境 profile 控制。
- 双方授权后才对账：只有发起者和执行者都授权，系统才读取双方 Todo Projection。
- 执行者不能直接覆盖发起者 Todo：执行者修改 DDL、标题、描述会进入 Change Proposal。
- 重要字段进入审核流：deadline/title/description 需要发起者确认后才同步。
- LLM 不控制状态：LLM 只做结构化抽取，状态迁移只通过 state_machine.py。

## 7. 技术亮点

- FastAPI 后端：统一承接飞书事件、卡片回调和调试接口。
- Feishu/OpenClaw 入口：飞书负责真实协作入口，OpenClaw 作为自然语言编排入口。
- Task Contract Ledger：记录跨人任务的合同态与状态流转。
- Todo Projection：把同一个合同投影到个人视图，避免超级权限式集中覆盖。
- Resource Ranking：把参考资料分为 high_confidence 和 low_confidence。
- Progress Query：群聊问进度时先问执行者确认，再回复摘要。
- Reconciliation：对账双方 Projection，按字段归属生成审核卡片。

## 8. 当前边界

- 默认 dry-run：本地默认 `FEISHU_MOCK=true`、`LARK_DRY_RUN=true`。
- 真实试用仅白名单：`production_trial` 必须配置 `ALLOWED_USER_IDS` 和 `ALLOWED_CHAT_IDS`。
- 真实读写需显式开启：需要关闭 mock/dry-run，并配置飞书应用、Bitable、scope 和 verification token。
- OpenClaw 还未真实发布：当前提供 manifest、README 和示例 prompt，后续可发布为正式 OpenClaw Skill。

## 9. 现场演示命令

```powershell
python demo/demo_smoke_test.py
```

这条命令会在本地 mock 模式下跑完：

1. 创建 mock 用户
2. 提交会议纪要事件
3. 生成任务候选
4. 发起者确认
5. 执行者接受
6. 资源推荐
7. 进度查询
8. 执行者确认进度
9. 对账发现差异
10. 审核并输出最终 summary
