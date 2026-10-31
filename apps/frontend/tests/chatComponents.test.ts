// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage, ChatSessionSummary, ToolCallAudit } from "@agent-py/api-contracts";

import ChatComposer from "../src/components/ChatComposer.vue";
import ChatMemoryPanel from "../src/components/ChatMemoryPanel.vue";
import ChatSessionList from "../src/components/ChatSessionList.vue";
import ChatTranscript from "../src/components/ChatTranscript.vue";
import RetrievalStageTrace from "../src/components/RetrievalStageTrace.vue";

beforeEach(() => {
  setActivePinia(createPinia());
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true, data: { items: [] } }), {
    headers: { "Content-Type": "application/json" },
    status: 200
  })));
});

const sessions: readonly ChatSessionSummary[] = [
  {
    id: "chat_1",
    ownerUserId: "user_1",
    title: "Restart API",
    createdAt: "2026-07-10T00:00:00.000Z",
    updatedAt: "2026-07-10T00:01:00.000Z",
    memory: {
      mode: "every_30_turns",
      contextTokens: 1200,
      contextWindowTokens: 131072,
      contextUsagePercent: 0.9,
      compactedMessageCount: 0,
      lastCompactedAt: null,
      canCompact: true
    }
  }
];

const assistantMessage: ChatMessage = {
  id: "message_1",
  ownerUserId: "user_1",
  sessionId: "chat_1",
  role: "assistant",
  content: "Use the **runbook**.",
  metadata: {
    citations: [
      {
        id: "reference_1",
        title: "Restart runbook",
        sourceType: "document",
        knowledgeType: "sop",
        documentId: "doc_1",
        knowledgeBaseId: "kb_1",
        excerpt: "Restart the API after validating the deployment health.",
        metadata: { section: "restart" },
        score: 0.94,
        vectorRank: 2,
        vectorScore: 0.87,
        bm25Rank: 1,
        bm25Score: 4.21,
        rrfScore: 2 / 61,
        rerankRank: 1,
        rerankScore: 0.94
      }
    ],
    toolCallIds: ["tool_1"],
    reasoning: ["先确认运行手册，再给出结论。"]
  },
  createdAt: "2026-07-10T00:01:00.000Z"
};

const audits: readonly ToolCallAudit[] = [
  {
    id: "tool_1",
    ownerUserId: "user_1",
    sessionId: "chat_1",
    diagnosticTaskId: null,
    toolName: "knowledge_retrieval",
    status: "completed",
    arguments: {},
    resultSummary: "Found 1 relevant chunk.",
    errorMessage: null,
    startedAt: "2026-07-10T00:00:01.000Z",
    completedAt: "2026-07-10T00:00:02.000Z",
    durationMs: 12,
    createdAt: "2026-07-10T00:00:01.000Z"
  }
];

const userMessage: ChatMessage = {
  id: "message_user_1",
  ownerUserId: "user_1",
  sessionId: "chat_1",
  role: "user",
  content: "帮我查一下最近 15 分钟的 ERROR 日志",
  metadata: {},
  createdAt: "2026-07-10T00:00:30.000Z"
};

describe("chat components", () => {
  it("renders the welcome greeting on an empty conversation without an accent mark", () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: false,
        isSending: false,
        liveToolCalls: [],
        messages: [],
        references: [],
        toolAudits: []
      }
    });

    expect(wrapper.find('[aria-label="助手欢迎信息"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("您好，我是值班助手");
    expect(wrapper.text()).toContain("日志与监控分析");
    expect(wrapper.text()).toContain("知识库检索");
    expect(wrapper.text()).toContain("时间与工具辅助");
    expect(wrapper.find(".chat-transcript__typing").exists()).toBe(false);
    expect(wrapper.find(".empty-state__mark").exists()).toBe(false);
  });

  it("hides the welcome greeting once any message exists", () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: false,
        isSending: false,
        liveToolCalls: [],
        messages: [assistantMessage],
        references: [],
        toolAudits: []
      }
    });

    expect(wrapper.find('[aria-label="助手欢迎信息"]').exists()).toBe(false);
    expect(wrapper.find(".chat-transcript__messages").exists()).toBe(true);
  });

  it("keeps the loading state instead of the welcome greeting while a conversation loads", () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: true,
        isSending: false,
        liveToolCalls: [],
        messages: [],
        references: [],
        toolAudits: []
      }
    });

    expect(wrapper.text()).toContain("正在加载对话");
    expect(wrapper.find('[aria-label="助手欢迎信息"]').exists()).toBe(false);
  });

  it("shows the typing indicator while sending and no assistant draft exists", () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: false,
        isSending: true,
        liveToolCalls: [],
        messages: [userMessage],
        references: [],
        toolAudits: []
      }
    });

    expect(wrapper.find('[aria-label="助手正在输入"]').exists()).toBe(true);
    expect(wrapper.findAll(".chat-transcript__typing-dot")).toHaveLength(3);
    expect(wrapper.text()).toContain("助手");
  });

  it("hides the typing indicator once an assistant draft message appears", () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: false,
        isSending: true,
        liveToolCalls: [],
        messages: [userMessage, { ...assistantMessage, id: "message_draft_1", content: "好", metadata: {} }],
        references: [],
        toolAudits: []
      }
    });

    expect(wrapper.find('[aria-label="助手正在输入"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("好");
  });

  it("does not render the typing indicator when no send is in progress", () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: false,
        isSending: false,
        liveToolCalls: [],
        messages: [userMessage],
        references: [],
        toolAudits: []
      }
    });

    expect(wrapper.find('[aria-label="助手正在输入"]').exists()).toBe(false);
  });

  it("sends with Enter while preserving Shift+Enter and IME composition", async () => {
    const wrapper = mount(ChatComposer, {
      props: {
        disabled: false,
        isSending: false,
        contextUsagePercent: 0
      }
    });
    const textarea = wrapper.get("textarea");

    await textarea.setValue("  你好  ");
    await textarea.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("send")).toEqual([["你好"]]);
    expect((textarea.element as HTMLTextAreaElement).value).toBe("");

    await textarea.setValue("第一行\n第二行");
    await textarea.trigger("keydown", { key: "Enter", shiftKey: true });
    expect(wrapper.emitted("send")).toHaveLength(1);
    expect((textarea.element as HTMLTextAreaElement).value).toBe("第一行\n第二行");

    await textarea.setValue("拼音输入中");
    await textarea.trigger("keydown", { key: "Enter", isComposing: true });
    expect(wrapper.emitted("send")).toHaveLength(1);
    expect((textarea.element as HTMLTextAreaElement).value).toBe("拼音输入中");
  });

  it("blocks input at 95 percent context usage", () => {
    const wrapper = mount(ChatComposer, {
      props: {
        disabled: false,
        isSending: false,
        contextUsagePercent: 95
      }
    });

    expect(wrapper.text()).toContain("上下文已达到 95%，请执行手动压缩");
    expect(wrapper.get("textarea").attributes("disabled")).toBeDefined();
    expect(wrapper.get('button[aria-label="发送消息"]').attributes("disabled")).toBeDefined();
  });

  it("shows session memory usage and applies a mode from the settings panel", async () => {
    const wrapper = mount(ChatMemoryPanel, {
      props: {
        isUpdatingMemory: false,
        memory: { ...sessions[0]!.memory, contextUsagePercent: 95 }
      }
    });

    expect(wrapper.text()).toContain("95%");
    await wrapper.get("select").setValue("context_70_percent");
    await wrapper.get(".chat-memory__apply").trigger("click");
    expect(wrapper.emitted("applyMemory")).toEqual([["context_70_percent"]]);
  });

  it("offers manual compaction from the memory panel", async () => {
    const wrapper = mount(ChatMemoryPanel, {
      props: {
        isUpdatingMemory: false,
        memory: { ...sessions[0]!.memory, mode: "manual" }
      }
    });

    await wrapper.get(".chat-memory__apply").trigger("click");
    expect(wrapper.emitted("compactMemory")).toHaveLength(1);
  });

  it("marks the selected session and emits session commands", async () => {
    const wrapper = mount(ChatSessionList, { props: { activeSessionId: "chat_1", sessions, variant: "rail" } });

    expect(wrapper.classes()).toContain("chat-session-list--rail");
    expect(wrapper.get('[aria-current="page"]').text()).toContain("Restart API");
    await wrapper.get('button[title="新建对话"]').trigger("click");
    expect(wrapper.emitted("create")).toHaveLength(1);
    await wrapper.get(".chat-session-list__select").trigger("click");
    expect(wrapper.emitted("select")).toEqual([["chat_1"]]);
    await wrapper.get('button[title="删除 Restart API"]').trigger("click");
    expect(wrapper.emitted("delete")).toEqual([["chat_1"]]);
  });

  it("renders Markdown, source titles, detailed citation evidence, and tool result summaries", async () => {
    const wrapper = mount(ChatTranscript, {
      props: {
        isLoading: false,
        liveToolCalls: [],
        messages: [assistantMessage],
        references: assistantMessage.metadata.citations ?? [],
        toolAudits: audits
      }
    });

    expect(wrapper.text()).toContain("runbook");
    expect(wrapper.text()).toContain("Restart runbook");
    expect(wrapper.text()).toContain("Found 1 relevant chunk.");
    expect(wrapper.text()).toContain("工具调用");
    expect(wrapper.text()).toContain("深度思考");
    expect(wrapper.text()).toContain("先确认运行手册，再给出结论。");
    expect(wrapper.text()).toContain("向量#2 · 87%");
    expect(wrapper.text()).toContain("BM25#1 · 4.210");
    expect(wrapper.text()).toContain("精排#1 · 94%");
    const citation = wrapper.get('button[aria-label="查看 Restart runbook 的来源详情"]');
    await citation.trigger("click");
    expect(wrapper.text()).toContain("Restart the API after validating the deployment health.");
    expect(wrapper.text()).toContain("SOP");
    await wrapper.get('button[aria-label="在知识库中打开 Restart runbook"]').trigger("click");
    expect(wrapper.emitted("open-document")?.[0]?.[0]).toMatchObject({ documentId: "doc_1" });
  });

  it("shows an explicit un-recalled state for a missing coarse retrieval stage", () => {
    const wrapper = mount(RetrievalStageTrace, {
      props: {
        reference: {
          id: "reference_keyword_only",
          title: "Exact error code",
          sourceType: "knowledge-base",
          bm25Rank: 1,
          bm25Score: 8.63,
          rerankRank: 2,
          rerankScore: 0.91
        }
      }
    });

    expect(wrapper.text()).toContain("向量未召回");
    expect(wrapper.text()).toContain("BM25#1 · 8.630");
    expect(wrapper.text()).toContain("精排#2 · 91%");
  });
});
