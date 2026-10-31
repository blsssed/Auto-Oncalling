## REMOVED Requirements

### Requirement: Empty chat transcript remains blank

（由「New conversation welcome greeting」取代：空对话不再保持空白，而是展示助手能力欢迎信息。）

## ADDED Requirements

### Requirement: New conversation welcome greeting

聊天工作区 SHALL 在当前会话没有消息、未在加载且未在发送时，于记录区渲染一条助手欢迎信息，包含助手头像与中文能力说明（日志与监控分析、知识库检索、时间与工具辅助）；出现任意消息或进入发送/加载状态时 SHALL 隐藏。

#### Scenario: User opens a new empty conversation

- **WHEN** 当前会话消息数组为空且加载已完成
- **THEN** transcript MUST 渲染助手欢迎信息（头像 + 能力说明），MUST NOT 渲染 `.empty-state__mark`

#### Scenario: First message arrives

- **WHEN** 会话中出现任意用户或助手消息
- **THEN** 欢迎信息 MUST 隐藏，正常渲染消息列表

#### Scenario: Conversation is loading

- **WHEN** 当前会话仍在加载
- **THEN** transcript MUST 继续显示加载状态，不得用欢迎信息替代加载反馈

## MODIFIED Requirements

### Requirement: Responsive chat feedback states

聊天工作区 SHALL 在桌面和窄版布局中提供中文的会话空状态、历史加载中状态、发送进行中状态、来源、工具活动和错误状态。在桌面布局中，对话外壳 SHALL 会使用可用的视口高度，并将消息滚动限制在转录区域，同时保持会话控制和创作器可用。

#### Scenario: User has no conversations

- **WHEN** 后端返回一个空的会话集合
- **THEN** 工作区 MUST 渲染一个空的对话状态，并提供一个可用的命令以开始新的对话。

#### Scenario: Send is in progress

- **WHEN** 一个聊天发送正在进行中且助手草稿尚未出现首个内容字符
- **THEN** 记录区 MUST 展示助手头像与三点打字指示；首个内容字符到达后 MUST 以真实流式内容取代该指示；`prefers-reduced-motion: reduce` 时指示 MUST NOT 使用动画

#### Scenario: Long desktop conversation remains contained

- **WHEN** 一个桌面对话的消息足够多，以至于超过了可见的工作区高度  
- **THEN** 会话列表、对话头和创作者 MUST 在仅对话区域垂直滚动且页面 MUST NOT 随消息列表增长时仍保持可用。

#### Scenario: Narrow screen renders chat controls

- **WHEN** 在窄视口下查看工作区
- **THEN** 会话选择、传记、创作器、源列表和工具活动控件 MUST 在不出现水平溢出的情况下仍可读且可操作。
