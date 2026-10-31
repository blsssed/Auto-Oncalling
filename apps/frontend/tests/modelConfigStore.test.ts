import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";

import type { LlmConfigurationResponse } from "@agent-py/api-contracts";

import type { ConfigCheckReport, ModelConfigClient } from "../src/settings/modelConfigClient";
import {
  setModelConfigClientFactoryForTests,
  useModelConfigStore
} from "../src/stores/modelConfig";
import { useFeedbackStore } from "../src/stores/feedback";

const configuration: LlmConfigurationResponse = {
  provider: "qwen-openai",
  apiKeyConfigured: true,
  apiKeyLast4: "abcd",
  baseUrl: "https://provider.test/v1",
  chatModel: "qwen-test",
  contextWindowTokens: 131072,
  embeddingModel: "embedding-test",
  embeddingDimensions: 2,
  rerankModel: "rerank-test",
  rerankUrl: "https://provider.test/rerank",
  temperature: 0.2,
  timeoutSeconds: 120,
  maxRetries: 2,
  langfuseEnabled: false,
  langfuseHost: null,
  langfusePublicKeyConfigured: false,
  langfusePublicKeyLast4: null,
  langfuseSecretKeyConfigured: true,
  langfuseSecretKeyLast4: "cret"
};

const report: ConfigCheckReport = {
  status: "ready",
  configuration: { llm: { valid: true, model: "qwen-test", error: null } },
  dependencies: { llm: { ok: true, model: "qwen-test", latencyMs: 12, error: null } }
};

function fakeClient(
  overrides: Partial<ModelConfigClient> = {},
  calls: { updated: unknown[]; checked: number } = { updated: [], checked: 0 }
): ModelConfigClient {
  return {
    getConfiguration: async () => configuration,
    updateConfiguration: async (request) => {
      calls.updated.push(request);
      return { ...configuration, ...("apiKey" in request ? { apiKeyConfigured: true } : {}), baseUrl: request.baseUrl, chatModel: request.chatModel };
    },
    checkRuntime: async () => {
      calls.checked += 1;
      return report;
    },
    ...overrides
  };
}

afterEach(() => setModelConfigClientFactoryForTests(null));

describe("model config store", () => {
  it("loads the masked configuration without exposing an apiKey field", async () => {
    setActivePinia(createPinia());
    setModelConfigClientFactoryForTests(() => fakeClient());
    const store = useModelConfigStore();

    await store.initialize();

    expect(store.configuration).toEqual(configuration);
    expect(Object.hasOwn(store.configuration as unknown as Record<string, unknown>, "apiKey")).toBe(false);
    expect(store.isLoading).toBe(false);
  });

  it("saves the configuration, refreshes the runtime report and reports success", async () => {
    setActivePinia(createPinia());
    const calls = { updated: [] as unknown[], checked: 0 };
    setModelConfigClientFactoryForTests(() => fakeClient({}, calls));
    const store = useModelConfigStore();

    await store.save({
      baseUrl: "https://provider.test/v2",
      chatModel: "qwen-new",
      contextWindowTokens: 65536,
      embeddingModel: "embedding-new",
      embeddingDimensions: 4,
      rerankModel: "rerank-new",
      rerankUrl: "https://provider.test/rerank2",
      temperature: 0.5,
      timeoutSeconds: 30,
      maxRetries: 3
    });

    expect(calls.updated).toHaveLength(1);
    expect(calls.checked).toBe(1);
    expect(store.configuration?.chatModel).toBe("qwen-new");
    expect(store.runtimeReport).toEqual(report);
    expect(useFeedbackStore().current?.kind).toBe("success");
    expect(store.isSaving).toBe(false);
  });

  it("stores the runtime report from checkRuntime", async () => {
    setActivePinia(createPinia());
    setModelConfigClientFactoryForTests(() => fakeClient());
    const store = useModelConfigStore();

    await store.checkRuntime();

    expect(store.runtimeReport).toEqual(report);
    expect(store.isChecking).toBe(false);
  });

  it("surfaces errors through the shared feedback channel", async () => {
    setActivePinia(createPinia());
    setModelConfigClientFactoryForTests(() =>
      fakeClient({
        getConfiguration: async () => {
          throw new Error("boom");
        }
      })
    );
    const store = useModelConfigStore();

    await expect(store.initialize()).rejects.toThrow();
    expect(useFeedbackStore().current?.kind).toBe("error");
    expect(store.isLoading).toBe(false);
  });

  it("reset clears configuration and runtime report", async () => {
    setActivePinia(createPinia());
    setModelConfigClientFactoryForTests(() => fakeClient());
    const store = useModelConfigStore();

    await store.initialize();
    await store.checkRuntime();
    store.reset();

    expect(store.configuration).toBeNull();
    expect(store.runtimeReport).toBeNull();
  });
});
