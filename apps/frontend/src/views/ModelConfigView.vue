<script setup lang="ts">
import { CheckCircle2, RefreshCw, Save, TriangleAlert } from "lucide-vue-next";
import { computed, onMounted, reactive, watch } from "vue";

import type { LlmConfigurationResponse, UpdateLlmConfigurationRequest } from "@agent-py/api-contracts";

import AppLoadingState from "../components/AppLoadingState.vue";
import { useFeedbackStore } from "../stores/feedback";
import { useModelConfigStore } from "../stores/modelConfig";

const modelConfig = useModelConfigStore();
const feedback = useFeedbackStore();

const draft = reactive({
  apiKey: "",
  baseUrl: "",
  chatModel: "",
  contextWindowTokens: 131072,
  embeddingModel: "",
  embeddingDimensions: 1024,
  rerankModel: "",
  rerankUrl: "",
  temperature: 0.2,
  timeoutSeconds: 120,
  maxRetries: 2,
  langfuseEnabled: false,
  langfuseHost: "",
  langfusePublicKey: "",
  langfuseSecretKey: ""
});

function syncDraft(configuration: LlmConfigurationResponse): void {
  Object.assign(draft, {
    apiKey: "",
    baseUrl: configuration.baseUrl,
    chatModel: configuration.chatModel,
    contextWindowTokens: configuration.contextWindowTokens ?? 131072,
    embeddingModel: configuration.embeddingModel,
    embeddingDimensions: configuration.embeddingDimensions,
    rerankModel: configuration.rerankModel,
    rerankUrl: configuration.rerankUrl,
    temperature: configuration.temperature,
    timeoutSeconds: configuration.timeoutSeconds,
    maxRetries: configuration.maxRetries,
    langfuseEnabled: configuration.langfuseEnabled,
    langfuseHost: configuration.langfuseHost ?? "",
    langfusePublicKey: "",
    langfuseSecretKey: ""
  });
}

watch(() => modelConfig.configuration, (configuration) => {
  if (configuration !== null) syncDraft(configuration);
}, { immediate: true });

onMounted(() => { void modelConfig.initialize().catch(() => undefined); });

const isDirty = computed(() => {
  const configuration = modelConfig.configuration;
  if (configuration === null) return false;
  return (
    draft.apiKey.trim() !== "" ||
    draft.baseUrl !== configuration.baseUrl ||
    draft.chatModel !== configuration.chatModel ||
    draft.contextWindowTokens !== (configuration.contextWindowTokens ?? 131072) ||
    draft.embeddingModel !== configuration.embeddingModel ||
    draft.embeddingDimensions !== configuration.embeddingDimensions ||
    draft.rerankModel !== configuration.rerankModel ||
    draft.rerankUrl !== configuration.rerankUrl ||
    draft.temperature !== configuration.temperature ||
    draft.timeoutSeconds !== configuration.timeoutSeconds ||
    draft.maxRetries !== configuration.maxRetries ||
    draft.langfuseEnabled !== configuration.langfuseEnabled ||
    draft.langfuseHost.trim() !== (configuration.langfuseHost ?? "") ||
    draft.langfusePublicKey.trim() !== "" ||
    draft.langfuseSecretKey.trim() !== ""
  );
});

const apiKeyPlaceholder = computed(() => {
  const configuration = modelConfig.configuration;
  return maskedKeyPlaceholder(
    configuration?.apiKeyConfigured === true,
    configuration?.apiKeyLast4,
    "首次使用请输入 API Key"
  );
});

const langfusePublicKeyPlaceholder = computed(() => {
  const configuration = modelConfig.configuration;
  return maskedKeyPlaceholder(
    configuration?.langfusePublicKeyConfigured === true,
    configuration?.langfusePublicKeyLast4,
    "首次使用请输入 PublicKey"
  );
});

const langfuseSecretKeyPlaceholder = computed(() => {
  const configuration = modelConfig.configuration;
  return maskedKeyPlaceholder(
    configuration?.langfuseSecretKeyConfigured === true,
    configuration?.langfuseSecretKeyLast4,
    "首次使用请输入 SecretKey"
  );
});

function maskedKeyPlaceholder(
  configured: boolean | undefined,
  last4: string | null | undefined,
  firstTimeHint: string
): string {
  if (configured === true) {
    return `已配置（****${last4 ?? "****"}），留空保持不变`;
  }
  return firstTimeHint;
}

function buildRequest(): UpdateLlmConfigurationRequest {
  const apiKey = draft.apiKey.trim();
  const langfuseHost = draft.langfuseHost.trim();
  const langfusePublicKey = draft.langfusePublicKey.trim();
  const langfuseSecretKey = draft.langfuseSecretKey.trim();
  return {
    ...(apiKey === "" ? {} : { apiKey }),
    baseUrl: draft.baseUrl.trim(),
    chatModel: draft.chatModel.trim(),
    contextWindowTokens: draft.contextWindowTokens,
    embeddingModel: draft.embeddingModel.trim(),
    embeddingDimensions: draft.embeddingDimensions,
    rerankModel: draft.rerankModel.trim(),
    rerankUrl: draft.rerankUrl.trim(),
    temperature: draft.temperature,
    timeoutSeconds: draft.timeoutSeconds,
    maxRetries: draft.maxRetries,
    langfuseEnabled: draft.langfuseEnabled,
    ...(langfuseHost === "" ? {} : { langfuseHost }),
    ...(langfusePublicKey === "" ? {} : { langfusePublicKey }),
    ...(langfuseSecretKey === "" ? {} : { langfuseSecretKey })
  };
}

async function save(): Promise<void> {
  await modelConfig.save(buildRequest());
}

function run(operation: () => Promise<void>): void {
  void operation().catch(() => undefined);
}

function checkRuntime(): void {
  if (isDirty.value) {
    feedback.show("info", "表单有未保存的修改，请先保存后再测试连接。");
    return;
  }
  void modelConfig.checkRuntime().catch(() => undefined);
}

const llmConfiguration = computed(() => modelConfig.runtimeReport?.configuration.llm ?? null);
const llmDependency = computed(() => modelConfig.runtimeReport?.dependencies.llm ?? null);
</script>

<template>
  <section class="model-config" aria-label="模型配置">
    <header class="model-config__header">
      <div>
        <p>自助配置</p>
        <h2>模型配置</h2>
        <span>修改保存后立即生效，无需重启后端。提供方：{{ modelConfig.configuration?.provider ?? "qwen-openai" }}（只读）。</span>
      </div>
    </header>
    <AppLoadingState v-if="modelConfig.isLoading" label="正在加载模型配置" />
    <div v-else class="model-config__workspace">
      <form class="model-config__form" @submit.prevent="run(save)">
        <div class="model-config__fields">
          <label class="model-config__wide"><span>API Key</span>
            <input v-model.trim="draft.apiKey" type="password" autocomplete="new-password" :placeholder="apiKeyPlaceholder" maxlength="512" />
          </label>
          <label class="model-config__wide"><span>Base URL</span>
            <input v-model.trim="draft.baseUrl" type="url" required maxlength="512" />
          </label>
          <label><span>对话模型</span><input v-model.trim="draft.chatModel" required maxlength="128" /></label>
          <label><span>上下文窗口（tokens）</span><input v-model.number="draft.contextWindowTokens" type="number" min="1" required /></label>
          <label><span>Embedding 模型</span><input v-model.trim="draft.embeddingModel" required maxlength="128" /></label>
          <label><span>Embedding 维度</span><input v-model.number="draft.embeddingDimensions" type="number" min="1" required /></label>
          <label><span>Rerank 模型</span><input v-model.trim="draft.rerankModel" required maxlength="128" /></label>
          <label><span>Rerank URL</span><input v-model.trim="draft.rerankUrl" type="url" required maxlength="512" /></label>
          <label><span>温度（0–2）</span><input v-model.number="draft.temperature" type="number" min="0" max="2" step="0.1" required /></label>
          <label><span>超时（秒）</span><input v-model.number="draft.timeoutSeconds" type="number" min="1" max="600" required /></label>
          <label><span>重试次数</span><input v-model.number="draft.maxRetries" type="number" min="1" required /></label>
          <p class="model-config__section">Langfuse 追踪（可选）</p>
          <label class="model-config__wide model-config__toggle">
            <input v-model="draft.langfuseEnabled" type="checkbox" />
            <span>启用 Langfuse 追踪（需同时填写 PublicKey 与 SecretKey）</span>
          </label>
          <label class="model-config__wide"><span>Langfuse Host（留空使用默认云端地址）</span>
            <input v-model.trim="draft.langfuseHost" type="url" maxlength="512" placeholder="https://cloud.langfuse.com" />
          </label>
          <label><span>Langfuse PublicKey</span>
            <input v-model.trim="draft.langfusePublicKey" type="password" autocomplete="new-password" :placeholder="langfusePublicKeyPlaceholder" maxlength="512" />
          </label>
          <label><span>Langfuse SecretKey</span>
            <input v-model.trim="draft.langfuseSecretKey" type="password" autocomplete="new-password" :placeholder="langfuseSecretKeyPlaceholder" maxlength="512" />
          </label>
        </div>
        <div class="model-config__commands">
          <button type="button" :disabled="modelConfig.isChecking" @click="checkRuntime">
            <RefreshCw :size="15" aria-hidden="true" />{{ modelConfig.isChecking ? "检测中" : "测试连接" }}
          </button>
          <button type="submit" class="model-config__save" :disabled="modelConfig.isSaving">
            <Save :size="15" aria-hidden="true" />{{ modelConfig.isSaving ? "保存中" : "保存配置" }}
          </button>
        </div>
      </form>

      <aside class="model-config__status" aria-label="运行状态">
        <h3>运行状态</h3>
        <p v-if="modelConfig.runtimeReport === null" class="model-config__empty">
          点击「测试连接」或保存配置后，这里会展示后端配置校验与依赖探测的真实结果。
        </p>
        <template v-else>
          <div class="model-config__row">
            <span>整体状态</span>
            <strong>{{ modelConfig.runtimeReport.status === "ready" ? "就绪" : "降级" }}</strong>
          </div>
          <div class="model-config__row">
            <span>配置校验</span>
            <strong :class="llmConfiguration?.valid ? 'model-config__ok' : 'model-config__bad'">
              {{ llmConfiguration?.valid ? "合法" : "不合法" }}
            </strong>
          </div>
          <div class="model-config__row">
            <span>当前模型</span>
            <strong>{{ llmConfiguration?.model ?? llmDependency?.model ?? "未知" }}</strong>
          </div>
          <div class="model-config__row">
            <span>依赖连通</span>
            <strong :class="llmDependency?.ok ? 'model-config__ok' : 'model-config__bad'">
              <CheckCircle2 v-if="llmDependency?.ok" :size="15" aria-hidden="true" />
              <TriangleAlert v-else :size="15" aria-hidden="true" />
              {{ llmDependency?.ok ? "连通" : "异常" }}
            </strong>
          </div>
          <p v-if="llmDependency?.latencyMs !== undefined" class="model-config__latency">
            探测延迟 {{ llmDependency.latencyMs }} ms
          </p>
          <p v-if="(llmConfiguration?.error ?? llmDependency?.error) !== null && (llmConfiguration?.error ?? llmDependency?.error) !== undefined" class="model-config__error">
            {{ llmConfiguration?.error ?? llmDependency?.error }}
          </p>
        </template>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.model-config { display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; }
.model-config__header { border-bottom: 1px solid var(--line); padding: 0 0 1rem; }
.model-config__header p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em; margin: 0 0 0.18rem; }
.model-config__header h2 { font-size: 1.08rem; font-weight: 600; margin: 0 0 0.25rem; }
.model-config__header span { color: var(--text-secondary); font-size: 0.8rem; }
.model-config__workspace { display: grid; gap: 1.2rem; grid-template-columns: minmax(0, 1fr) 17rem; margin-top: 1.1rem; }
.model-config__fields { display: grid; gap: 0.8rem 1rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.model-config__fields label { display: grid; gap: 0.3rem; }
.model-config__fields .model-config__wide { grid-column: span 2; }
.model-config__fields span { color: var(--text-secondary); font-size: 0.78rem; font-weight: 600; }
.model-config__section { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em; grid-column: span 2; margin: 0.4rem 0 0; }
.model-config__fields .model-config__toggle { align-items: center; display: flex; flex-direction: row; gap: 0.45rem; }
.model-config__fields .model-config__toggle input { width: 0.95rem; }
.model-config__fields input { background: var(--canvas); border: 1px solid var(--line); border-radius: var(--radius-sm); color: var(--text-primary); font-size: 0.85rem; min-height: 2rem; padding: 0 0.65rem; }
.model-config__fields input:focus { border-color: var(--accent); outline: none; }
.model-config__commands { display: flex; gap: 0.7rem; justify-content: flex-end; margin-top: 1.1rem; }
.model-config__commands button { align-items: center; background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--radius-sm); color: var(--text-primary); cursor: pointer; display: inline-flex; font-size: 0.82rem; font-weight: 600; gap: 0.4rem; min-height: 2rem; padding: 0 0.9rem; }
.model-config__commands button:disabled { cursor: not-allowed; opacity: 0.55; }
.model-config__commands .model-config__save { background: var(--accent-solid); border-color: var(--accent-solid); color: #fff; }
.model-config__status { background: var(--canvas); border: 1px solid var(--line); border-radius: var(--radius-md); display: flex; flex-direction: column; gap: 0.6rem; padding: 0.9rem 1rem; }
.model-config__status h3 { font-size: 0.86rem; font-weight: 600; margin: 0; }
.model-config__row { align-items: center; display: flex; justify-content: space-between; gap: 0.6rem; }
.model-config__row span { color: var(--text-tertiary); font-size: 0.76rem; }
.model-config__row strong { align-items: center; display: inline-flex; font-size: 0.8rem; gap: 0.3rem; }
.model-config__ok { color: var(--status-success-text); }
.model-config__bad { color: var(--status-danger-text); }
.model-config__latency, .model-config__empty, .model-config__error { color: var(--text-tertiary); font-size: 0.76rem; margin: 0; }
.model-config__error { color: var(--status-danger-text); }
@media (max-width: 760px) { .model-config__workspace { grid-template-columns: minmax(0, 1fr); } .model-config__fields { grid-template-columns: minmax(0, 1fr); } .model-config__fields .model-config__wide { grid-column: span 1; } }
</style>
