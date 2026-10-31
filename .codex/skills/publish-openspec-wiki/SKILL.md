---
name: publish-openspec-wiki
description: 将 OpenSpec change 的生命周期状态映射到 docs/changes WIKI 文档。新建 change 后生成 active 页面，归档后迁移为 archive 页面，并同步索引和 Sidebar、检查 delta specs 与 include 链接。遇到 openspec new、openspec archive 或需要全量校准 docs/changes 时使用。
---

# 发布 OpenSpec 变更到 WIKI

确保 OpenSpec change 与 `docs/changes/` 中对应的 WIKI 内容始终一致。

## 何时执行

| OpenSpec 状态变化 | WIKI 动作 |
|-------------------|-----------|
| 新建 change | 在 `docs/changes/active/` 生成页面 |
| change 已归档 | 将页面迁移到 `docs/changes/archive/` |

## 固定执行入口

在仓库根目录运行：

```bash
python3 .codex/skills/publish-openspec-wiki/scripts/sync_wiki.py active <change-name>
python3 .codex/skills/publish-openspec-wiki/scripts/sync_wiki.py archive <change-name-or-archive-name>
python3 .codex/skills/publish-openspec-wiki/scripts/sync_wiki.py all
```

使用脚本统一生成或刷新变更页面、索引与 Sidebar，同时分别核验 delta specs、include 引用目标以及导航数据是否一致。完成归档同步后，仍要执行 `npm run docs:build`。

## 执行流程

### 新建 change 后

1. **确认 change 可用**：验证 `openspec/changes/{name}/` 确实存在。
2. **生成 active 页面**：在 `docs/changes/active/{name}/index.md` 写入 VitePress `@include`，分别引用 proposal、design、tasks 和 delta specs。仓库通过符号链接 `docs/openspec` → `openspec` 暴露这些内容。
3. **登记 Sidebar**：把新页面加入 `docs/.vitepress/config.mts` 的“进行中”分组。
4. **刷新总索引**：让 `docs/changes/index.md` 反映最新 active change。
5. **核对 include**：逐项确认页面引用的目标文件都能找到。
6. **汇报结果**：说明已完成的同步项与验证结论。

### change 归档后

1. **定位归档目录**：在 `openspec/changes/archive/` 中匹配目标；既接受带日期的完整目录名，也允许用简短名称自动匹配日期前缀。
2. **严格核验 delta specs**：
   - 若归档目录不存在 specs，立即停止，并要求补建或由用户明确选择跳过。
   - 若 delta specs 尚未合并到 main specs，先让用户决定同步还是跳过。
   - 只有收到用户明确的跳过指令后，才允许向脚本传入 `--allow-unsynced`。
3. **迁移或补建 archive 页面**：把 active 页面移到 `docs/changes/archive/{date}-{name}/`，并将 frontmatter 更新为归档状态。
   - frontmatter 字段固定为 `title`、`status`、`createdDate`、`archivedDate`。
   - archive 页面中的 `@include` 必须落到 `../../../openspec/changes/archive/{date}-{name}/...`。
   - 不得留下 `../../../openspec/changes/{name}/...` 这类归档前引用。
4. **调整 Sidebar**：从“进行中”删除对应条目，再加入“已归档”分组。
5. **重建索引**：更新 `docs/changes/index.md`，并让条目排序与 Sidebar 对齐。
6. **检查 include 完整性**：任何引用目标不存在都应阻断流程。
7. **完成构建校验**：运行 `npm run docs:build`；即使构建成功，也要保留对 include 目标的独立检查结果。
8. **汇报结果**：总结页面迁移、导航更新、delta specs 检查和构建情况。

### 页面约定

WIKI 页面用 VitePress frontmatter 描述状态，并通过 include 指令嵌入 OpenSpec change 文件。

Active 页面 frontmatter：

```yaml
---
title: change-title
status: active
createdDate: YYYY-MM-DD
---
```

Archive 页面 frontmatter：

```yaml
---
title: change-title
status: archived
createdDate: YYYY-MM-DD
archivedDate: YYYY-MM-DD
---
```

include 示例：

```markdown
<!--@include: ../../../openspec/changes/archive/YYYY-MM-DD-change-title/proposal.md-->
```

## 边界与约束

- 保留 OpenSpec 原始 artifacts，仅新增或迁移 WIKI 页面。
- 始终用相对路径的 `@include` 引用 OpenSpec 内容。
- 执行变更前先确认路径有效；遇到失败时给出明确原因和可操作的恢复方式。
- archive 同步必须检查 delta specs 是否存在、是否已同步。
- archive 页面不得继续指向归档前的 `openspec/changes/{name}/`。
- 不得把 VitePress 构建成功等同于 include 有效，必须另行检查所有引用目标。
- 保持 `docs/changes/index.md`、`docs/.vitepress/config.mts`、`docs/changes/` 和 `openspec/changes/` 四处状态一致。
