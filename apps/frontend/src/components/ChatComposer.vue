<script setup lang="ts">
import { ArrowUp, LoaderCircle } from "lucide-vue-next";
import { computed, nextTick, ref } from "vue";

const emit = defineEmits<{
  send: [content: string];
}>();
const props = defineProps<{
  readonly disabled: boolean;
  readonly isSending: boolean;
  readonly contextUsagePercent: number;
}>();

const content = ref("");
const textarea = ref<HTMLTextAreaElement | null>(null);
const isHardLimited = computed(() => props.contextUsagePercent >= 95);
const inputDisabled = computed(() => props.disabled || props.isSending || isHardLimited.value);

// 输入框随内容自动增高，最高 12rem 后转为内部滚动。
const MAX_HEIGHT_PX = 12 * 16;

function resize(): void {
  const element = textarea.value;
  if (element === null) return;
  element.style.height = "auto";
  element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT_PX)}px`;
}

function submit(): void {
  const nextContent = content.value.trim();
  if (nextContent.length === 0 || inputDisabled.value) return;
  emit("send", nextContent);
  content.value = "";
  void nextTick(() => {
    const element = textarea.value;
    if (element !== null) element.style.height = "";
  });
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  submit();
}
</script>

<template>
  <form class="chat-composer" @submit.prevent="submit">
    <label class="chat-composer__label" for="chat-message">输入问题</label>
    <div class="chat-composer__field">
      <textarea
        id="chat-message"
        ref="textarea"
        v-model="content"
        rows="2"
        placeholder="向 Super AI 描述你正在处理的问题"
        :disabled="inputDisabled"
        @input="resize"
        @keydown="handleKeydown"
      />
      <button type="submit" title="发送消息" aria-label="发送消息" :disabled="inputDisabled || !content.trim()">
        <LoaderCircle v-if="isSending" class="chat-composer__spin" :size="18" aria-hidden="true" />
        <ArrowUp v-else :size="18" aria-hidden="true" />
      </button>
    </div>
    <div class="chat-composer__meta">
      <span class="chat-composer__hint">Enter 发送，Shift+Enter 换行</span>
      <span v-if="isSending" class="chat-composer__status" role="status" aria-live="polite">正在生成回答，请稍候</span>
      <span v-else-if="isHardLimited" class="chat-composer__limit" role="alert">上下文已达到 95%，请执行手动压缩</span>
    </div>
  </form>
</template>

<style scoped>
.chat-composer { background: linear-gradient(to top, var(--surface-raised) 72%, var(--surface-raised-fade)); display: grid; gap: 0.45rem; padding: 1.5rem clamp(1rem, 5vw, 6rem) 1.2rem; }
.chat-composer__label { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 600; }
.chat-composer__field { align-items: end; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 1.5rem; display: grid; grid-template-columns: minmax(0, 1fr) auto; padding: 0.35rem; transition: border-color var(--transition-fast); }
.chat-composer__field:hover { border-color: var(--accent-border); }
textarea { background: transparent; border: 0; color: var(--text-primary); font-size: 0.92rem; line-height: 1.6; max-height: 12rem; min-height: 4rem; outline: 0; overflow-y: auto; padding: 0.78rem 0.55rem 0.62rem 0.9rem; resize: none; width: 100%; }
textarea::placeholder { color: var(--text-tertiary); }
.chat-composer__field button { align-items: center; align-self: end; background: var(--accent-solid); border-radius: 50%; color: #ffffff; display: inline-flex; height: 2.45rem; justify-content: center; margin: 0 0.18rem 0.18rem 0; transition: filter var(--transition-fast), transform var(--transition-fast), background var(--transition-fast); width: 2.45rem; }
.chat-composer__field button:hover:not(:disabled) { filter: brightness(1.1); transform: translateY(-1px); }
.chat-composer__field button:disabled { background: var(--line-strong); color: #ffffff; }
.chat-composer__meta { align-items: center; display: flex; justify-content: space-between; min-height: 1.1rem; padding: 0 0.4rem; }
.chat-composer__status { color: var(--status-running-text); font-size: 0.75rem; font-weight: 600; }
.chat-composer__limit { color: var(--status-danger-text); font-size: 0.75rem; font-weight: 600; }
.chat-composer__hint { color: var(--text-tertiary); font-size: 0.7rem; }
.chat-composer__spin { animation: chat-composer-spin 0.8s linear infinite; }
@keyframes chat-composer-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .chat-composer__spin { animation: none; } }
@media (max-width: 760px) { .chat-composer { padding: 1rem 0 0; } }
</style>
