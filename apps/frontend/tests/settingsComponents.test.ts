// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";

import type { LlmConfigurationResponse } from "@agent-py/api-contracts";

import type { ConfigCheckReport, ModelConfigClient } from "../src/settings/modelConfigClient";
import { setModelConfigClientFactoryForTests } from "../src/stores/modelConfig";
import { useFeedbackStore } from "../src/stores/feedback";
import { useAuthStore } from "../src/stores/auth";
import ModelConfigView from "../src/views/ModelConfigView.vue";
import PersonalInfoView from "../src/views/PersonalInfoView.vue";
import ProfileAboutView from "../src/views/ProfileAboutView.vue";
import ProfileView from "../src/views/ProfileView.vue";

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
  langfuseEnabled: true,
  langfuseHost: "https://cloud.langfuse.com",
  langfusePublicKeyConfigured: true,
  langfusePublicKeyLast4: "blic",
  langfuseSecretKeyConfigured: true,
  langfuseSecretKeyLast4: "cret"
};

const report: ConfigCheckReport = {
  status: "ready",
  configuration: { llm: { valid: true, model: "qwen-test", error: null } },
  dependencies: { llm: { ok: true, model: "qwen-test", latencyMs: 12, error: null } }
};

function fakeClient(overrides: Partial<ModelConfigClient> = {}): ModelConfigClient {
  return {
    getConfiguration: async () => configuration,
    updateConfiguration: async () => configuration,
    checkRuntime: async () => report,
    ...overrides
  };
}

function createProfileRouter(): ReturnType<typeof createRouter> {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      {
        path: "/profile",
        component: ProfileView,
        children: [
          { path: "model", component: ModelConfigView },
          { path: "info", component: PersonalInfoView },
          { path: "about", component: ProfileAboutView }
        ]
      }
    ]
  });
}

afterEach(() => setModelConfigClientFactoryForTests(null));

describe("profile center views", () => {
  it("renders the model config form with a masked apiKey placeholder", async () => {
    setActivePinia(createPinia());
    setModelConfigClientFactoryForTests(() => fakeClient());
    const wrapper = mount(ModelConfigView, { global: { plugins: [] } });
    await flushPromises();

    const apiKeyInput = wrapper.get('input[type="password"]');
    expect(apiKeyInput.attributes("placeholder")).toContain("****abcd");
    expect(apiKeyInput.attributes("placeholder")).toContain("留空保持不变");
    expect(wrapper.text()).toContain("qwen-openai");
    expect(wrapper.text()).not.toContain("apiKey");

    // Langfuse 密钥同样只显示掩码占位；启用状态与 host 回填到表单。
    const passwordInputs = wrapper.findAll('input[type="password"]');
    expect(passwordInputs).toHaveLength(3);
    expect(passwordInputs[1]!.attributes("placeholder")).toContain("****blic");
    expect(passwordInputs[2]!.attributes("placeholder")).toContain("****cret");
    const langfuseToggle = wrapper.get('input[type="checkbox"]');
    expect((langfuseToggle.element as HTMLInputElement).checked).toBe(true);
    expect(wrapper.text()).toContain("Langfuse 追踪");
  });

  it("blocks the connection test while the form has unsaved edits", async () => {
    setActivePinia(createPinia());
    let checked = 0;
    setModelConfigClientFactoryForTests(() =>
      fakeClient({ checkRuntime: async () => { checked += 1; return report; } })
    );
    const wrapper = mount(ModelConfigView);
    await flushPromises();

    await wrapper.get('input[type="password"]').setValue("brand-new-key");
    await wrapper.get('button[type="button"]').trigger("click");

    expect(checked).toBe(0);
    expect(useFeedbackStore().current?.message).toContain("请先保存");
  });

  it("shows the saved configuration status after checking the runtime", async () => {
    setActivePinia(createPinia());
    setModelConfigClientFactoryForTests(() => fakeClient());
    const wrapper = mount(ModelConfigView);
    await flushPromises();

    // 表单未修改时点击「测试连接」（第二个按钮，第一个是 submit 前的测试按钮）。
    const buttons = wrapper.findAll("button");
    const checkButton = buttons.find((button) => button.text().includes("测试连接"));
    await checkButton?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("就绪");
    expect(wrapper.text()).toContain("连通");
  });

  it("renders read-only account info and validates the new password locally", async () => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.user = {
      id: "user_1",
      email: "timi@example.com",
      displayName: "Timi",
      createdAt: "2026-07-08T00:00:00.000Z"
    };
    const wrapper = mount(PersonalInfoView);
    expect(wrapper.text()).toContain("timi@example.com");
    expect(wrapper.text()).toContain("Timi");

    const passwordForm = wrapper.get('form[aria-label="修改密码"]');
    const inputs = passwordForm.findAll("input");
    await inputs[0]!.setValue("correct horse battery staple");
    await inputs[1]!.setValue("short");
    await inputs[2]!.setValue("short");
    await passwordForm.trigger("submit");
    await flushPromises();

    expect(useFeedbackStore().current?.message).toContain("8");
  });

  it("renders the profile menu with all three entries", () => {
    const router = createProfileRouter();
    const wrapper = mount(ProfileView, {
      global: { plugins: [router] }
    });

    const links = wrapper.findAll(".profile-view__link");
    expect(links.map((link) => link.text())).toEqual(["模型配置", "个人信息", "关于"]);
    expect(links.map((link) => link.attributes("href"))).toEqual([
      "/profile/model",
      "/profile/info",
      "/profile/about"
    ]);
  });

  it("shows the backend connection state in the about view", async () => {
    const wrapper = mount(ProfileAboutView);
    await flushPromises();

    expect(wrapper.text()).toContain("super-ai-backend");
  });
});
