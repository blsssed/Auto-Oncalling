# 任务

## 1. 聊天记录组件

- [x] `ChatTranscript.vue` 新增 `isSending` prop（可选）。
- [x] 空会话（无消息、未加载、未发送）渲染助手欢迎信息：头像 + 能力说明。
- [x] 发送中且无助手草稿时渲染三点打字指示（助手头像 + 动画）。
- [x] `prefers-reduced-motion: reduce` 下打字指示不用动画。
- [x] `ChatView.vue` 传递 `is-sending`。

## 2. 测试

- [x] 用例：空会话展示欢迎信息且不渲染 `.empty-state__mark`。
- [x] 用例：出现消息后欢迎信息消失。
- [x] 用例：isSending 且无草稿时展示打字指示；有草稿后消失。
- [x] 用例：isSending 为 false 时不展示打字指示。

## 3. 验证

- [x] `npm run frontend:typecheck`、`npm run frontend:test`、`npm run frontend:build`
- [x] `openspec validate chat-welcome-and-typing-feedback`
