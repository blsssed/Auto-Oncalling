<script setup lang="ts">
import { BookOpen, Bot, Wrench } from "lucide-vue-next";
import { computed, ref } from "vue";

import type { ChatMessage, ToolCallAudit } from "@agent-py/api-contracts";
import type { ChatReference, LiveToolCall } from "../stores/chat";
import AppLoadingState from "./AppLoadingState.vue";
import AsyncStatusBadge from "./AsyncStatusBadge.vue";
import ChatCitationDetail from "./ChatCitationDetail.vue";
import MarkdownContent from "./MarkdownContent.vue";
import RetrievalStageTrace from "./RetrievalStageTrace.vue";
import UserFeedbackControl from "./UserFeedbackControl.vue";

const emit = defineEmits<{ "open-document": [reference: ChatReference] }>();
const props = defineProps<{
  readonly isLoading: boolean;
  readonly liveToolCalls: readonly LiveToolCall[];
  readonly messages: readonly ChatMessage[];
  readonly references: readonly ChatReference[];
  readonly toolAudits: readonly ToolCallAudit[];
  readonly isSending?: boolean;
}>();

const selectedCitation = ref<ChatReference | null>(null);
const selectedCitationMessageId = ref<string | null>(null);
const latestAssistantMessageId = computed(() =>
  [...props.messages].reverse().find((message) => message.role === "assistant")?.id ?? null
);
const showWelcome = computed(() =>
  props.messages.length === 0 && !props.isLoading && props.isSending !== true
);
const awaitingAnswer = computed(() =>
  props.isSending === true &&
  !props.messages.some((message) => message.id.startsWith("message_draft_"))
);

function selectCitation(reference: ChatReference, messageId: string | null): void {
  selectedCitation.value = reference;
  selectedCitationMessageId.value = messageId;
}

function canCollectFeedback(message: ChatMessage): boolean {
  return message.role === "assistant" && !message.id.startsWith("message_draft_");
}

function sourceLabel(reference: ChatReference): string {
  if (reference.knowledgeType === "sop") return "SOP";
  if (reference.knowledgeType === "diagnostic-case") return "故障案例";
  return reference.knowledgeType === "document" || reference.sourceType === "document"
    ? "知识库"
    : reference.sourceType;
}

function messageAudits(message: ChatMessage): readonly ToolCallAudit[] {
  const ids = new Set(message.metadata.toolCallIds ?? []);
  return props.toolAudits.filter((audit) => ids.has(audit.id));
}
</script>

<template>
  <section class="chat-transcript" aria-label="当前对话">
    <AppLoadingState v-if="isLoading" label="正在加载对话" />
    <aside v-else-if="showWelcome" class="chat-transcript__welcome" aria-label="助手欢迎信息">
      <span class="chat-transcript__welcome-avatar"><Bot :size="22" aria-hidden="true" /></span>
      <div class="chat-transcript__welcome-body">
        <h2>您好，我是值班助手</h2>
        <p>可以帮你处理运行中的各类问题，尤其擅长：</p>
        <ul>
          <li><strong>日志与监控分析（CLS）</strong>——检索和分析日志内容、查询指标趋势、排查告警策略与历史。</li>
          <li><strong>知识库检索</strong>——搜索已索引的文档知识并给出可追溯的引用。</li>
          <li><strong>时间与工具辅助</strong>——时间戳转换、地域代码查询等。</li>
        </ul>
        <p class="chat-transcript__welcome-hint">试着问：「帮我查一下最近 15 分钟的 ERROR 日志」「分析某个告警的触发原因」。</p>
      </div>
    </aside>
    <ol v-else-if="messages.length > 0" class="chat-transcript__messages">
      <li v-for="message in messages" :key="message.id" :class="`chat-transcript__message--${message.role}`">
        <article class="chat-transcript__message">
          <span class="chat-transcript__role"><Bot v-if="message.role === 'assistant'" :size="15" aria-hidden="true" />{{ message.role === "assistant" ? "助手" : "你" }}</span>
          <MarkdownContent v-if="message.role === 'assistant'" :content="message.content" />
          <p v-else>{{ message.content }}</p>
          <ul v-if="message.metadata.citations?.length" class="chat-transcript__message-sources" aria-label="回答引用来源">
            <li v-for="reference in message.metadata.citations" :key="reference.id"><button type="button" :aria-label="`查看 ${reference.title} 的来源详情`" @click="selectCitation(reference, message.id)"><BookOpen :size="13" aria-hidden="true" />{{ reference.title }}</button><RetrievalStageTrace :reference="reference" compact /><UserFeedbackControl v-if="canCollectFeedback(message)" target-type="citation" :target-id="message.id" :subject-id="reference.id" compact /></li>
          </ul>
          <UserFeedbackControl v-if="canCollectFeedback(message)" target-type="chat_message" :target-id="message.id" compact />
          <details v-if="message.role === 'assistant' && messageAudits(message).length" class="chat-transcript__details"><summary><Wrench :size="14" aria-hidden="true" />工具调用（{{ messageAudits(message).length }}）</summary><ul><li v-for="audit in messageAudits(message)" :key="audit.id"><span>{{ audit.toolName }}</span><AsyncStatusBadge :status="audit.status" compact /><small v-if="audit.resultSummary || audit.errorMessage">{{ audit.resultSummary ?? audit.errorMessage }}</small></li></ul></details>
          <details v-if="message.role === 'assistant' && message.metadata.reasoning?.length" class="chat-transcript__details"><summary>深度思考</summary><p>{{ message.metadata.reasoning.join('') }}</p></details>
        </article>
      </li>
    </ol>
    <div v-if="awaitingAnswer" class="chat-transcript__typing" aria-label="助手正在输入">
      <span class="chat-transcript__role"><Bot :size="15" aria-hidden="true" />助手</span>
      <div class="chat-transcript__typing-bubble" role="status">
        <span class="chat-transcript__typing-dot" />
        <span class="chat-transcript__typing-dot" />
        <span class="chat-transcript__typing-dot" />
      </div>
    </div>
    <aside v-if="liveToolCalls.length > 0" class="chat-transcript__context" aria-label="正在进行的工具调用">
      <h2><Wrench :size="15" aria-hidden="true" />工具调用</h2>
      <ul>
        <li v-for="tool in liveToolCalls" :key="tool.id"><span>{{ tool.name }}</span><AsyncStatusBadge :status="tool.status" compact /></li>
      </ul>
    </aside>
    <aside v-if="references.length > 0" class="chat-transcript__context" aria-label="本次回答引用的来源">
      <h2><BookOpen :size="15" aria-hidden="true" />本次回答引用</h2>
      <ul><li v-for="reference in references" :key="reference.id"><div class="chat-transcript__reference-heading"><span>{{ sourceLabel(reference) }}</span><button type="button" :aria-label="`查看 ${reference.title} 的来源详情`" @click="selectCitation(reference, latestAssistantMessageId)">{{ reference.title }}</button></div><RetrievalStageTrace :reference="reference" compact /><UserFeedbackControl v-if="latestAssistantMessageId" target-type="citation" :target-id="latestAssistantMessageId" :subject-id="reference.id" compact /></li></ul>
    </aside>
    <ChatCitationDetail v-if="selectedCitation && selectedCitationMessageId" :message-id="selectedCitationMessageId" :reference="selectedCitation" @close="selectedCitation = null; selectedCitationMessageId = null" @open-document="emit('open-document', $event)" />
  </section>
</template>

<style scoped>
.chat-transcript { display: grid; gap: 1.35rem; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 1.75rem clamp(1rem, 4vw, 4.5rem); scrollbar-color: var(--line-strong) transparent; }
.chat-transcript__messages { display: grid; gap: 1.4rem; list-style: none; margin: 0; padding: 0; }
.chat-transcript__message--user { display: flex; justify-content: flex-end; }
.chat-transcript__message { max-width: min(46rem, 90%); min-width: 0; }
.chat-transcript__role { align-items: center; color: var(--text-tertiary); display: inline-flex; font-size: 0.72rem; font-weight: 600; gap: 0.35rem; margin-bottom: 0.48rem; }
.chat-transcript__message p { line-height: 1.7; margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; word-break: break-word; }
.chat-transcript__message-sources { display: grid; gap: 0.6rem; list-style: none; margin: 0.85rem 0 0; padding: 0; }
.chat-transcript__message-sources li { display: grid; gap: 0.35rem; justify-items: start; }
.chat-transcript__message-sources li button { align-items: center; background: var(--accent-soft); border: 1px solid var(--accent-border); border-radius: 999px; color: var(--accent-strong); display: inline-flex; font-size: 0.74rem; font-weight: 600; gap: 0.3rem; padding: 0.28rem 0.48rem; }
.chat-transcript__message-sources li button:hover { background: var(--accent-border); }
.chat-transcript__details { border-top: 1px solid var(--line); color: var(--text-secondary); font-size: 0.78rem; margin-top: 0.8rem; padding-top: 0.65rem; }
.chat-transcript__details summary { align-items: center; cursor: pointer; display: flex; font-weight: 600; gap: 0.35rem; }
.chat-transcript__details ul { display: grid; gap: 0.4rem; list-style: none; margin: 0.65rem 0 0; padding: 0; }
.chat-transcript__details li { align-items: center; display: grid; gap: 0.45rem; grid-template-columns: minmax(0, 1fr) auto; }
.chat-transcript__details li small { color: var(--text-tertiary); grid-column: 1 / -1; overflow-wrap: anywhere; }
.chat-transcript__details p { color: var(--text-secondary); font-size: 0.78rem; line-height: 1.6; margin: 0.65rem 0 0; white-space: pre-wrap; }
.chat-transcript__context { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); max-width: 46rem; padding: 0.9rem 1rem; }
h2 { align-items: center; color: var(--text-secondary); display: flex; font-size: 0.78rem; font-weight: 600; gap: 0.42rem; margin: 0 0 0.7rem; }
.chat-transcript__context ul { display: grid; gap: 0.42rem; list-style: none; margin: 0; padding: 0; }
.chat-transcript__context li { display: grid; gap: 0.45rem; }
.chat-transcript__reference-heading { align-items: center; display: grid; gap: 0.5rem; grid-template-columns: auto minmax(0, 1fr); }
.chat-transcript__reference-heading > span { color: var(--text-tertiary); font-size: 0.7rem; }
.chat-transcript__reference-heading > button { font-size: 0.81rem; font-weight: 600; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.chat-transcript__reference-heading > button:hover { color: var(--accent-strong); text-decoration: underline; }
.chat-transcript__context li > span { align-items: center; display: grid; font-size: 0.81rem; gap: 0.25rem; grid-template-columns: auto minmax(0, 1fr); }
.chat-transcript__context li > span small { color: var(--text-secondary); font-size: 0.74rem; grid-column: 1 / -1; overflow-wrap: anywhere; }
.chat-transcript__context li > span svg { color: var(--accent-strong); }
.chat-transcript__context li > span svg + * { min-width: 0; }
.chat-transcript__welcome { align-items: start; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); display: flex; gap: 0.9rem; max-width: min(46rem, 90%); padding: 1.1rem 1.25rem; }
.chat-transcript__welcome-avatar { align-items: center; background: var(--accent-soft); border: 1px solid var(--accent-border); border-radius: 50%; color: var(--accent-strong); display: inline-flex; flex-shrink: 0; height: 2.4rem; justify-content: center; width: 2.4rem; }
.chat-transcript__welcome-body { color: var(--text-secondary); display: grid; gap: 0.45rem; min-width: 0; }
.chat-transcript__welcome-body h2 { color: var(--text-primary); font-size: 0.95rem; font-weight: 600; margin: 0; }
.chat-transcript__welcome-body p { line-height: 1.65; margin: 0; }
.chat-transcript__welcome-body ul { display: grid; gap: 0.35rem; list-style: none; margin: 0; padding: 0; }
.chat-transcript__welcome-body li { line-height: 1.6; padding-left: 0.9rem; position: relative; }
.chat-transcript__welcome-body li::before { background: var(--accent-solid); border-radius: 50%; content: ""; height: 0.3rem; left: 0; position: absolute; top: 0.55rem; width: 0.3rem; }
.chat-transcript__welcome-body strong { color: var(--text-primary); font-weight: 600; }
.chat-transcript__welcome-hint { color: var(--text-tertiary); }
.chat-transcript__typing { display: grid; gap: 0.48rem; justify-items: start; }
.chat-transcript__typing-bubble { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); display: inline-flex; gap: 0.32rem; padding: 0.7rem 0.85rem; }
.chat-transcript__typing-dot { animation: chat-typing-pulse 1.2s ease-in-out infinite; background: var(--text-tertiary); border-radius: 50%; height: 0.42rem; width: 0.42rem; }
.chat-transcript__typing-dot:nth-child(2) { animation-delay: 0.18s; }
.chat-transcript__typing-dot:nth-child(3) { animation-delay: 0.36s; }
@keyframes chat-typing-pulse { 0%, 100% { opacity: 0.3; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-0.12rem); } }
@media (prefers-reduced-motion: reduce) { .chat-transcript__typing-dot { animation: none; opacity: 0.6; } }
@media (max-width: 860px) { .chat-transcript { overflow-y: visible; } }
@media (max-width: 640px) { .chat-transcript { padding: 1.15rem 0; } .chat-transcript__message { max-width: 94%; } }
</style>
