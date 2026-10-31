import { ref } from "vue";
import { defineStore } from "pinia";

import type {
  LlmConfigurationResponse,
  UpdateLlmConfigurationRequest
} from "@agent-py/api-contracts";

import {
  createModelConfigClient,
  type ConfigCheckReport,
  type ModelConfigClient
} from "../settings/modelConfigClient";
import { toUserFacingError } from "../ui/userFacingError";
import { useFeedbackStore } from "./feedback";

let clientFactory: () => ModelConfigClient = createModelConfigClient;

export function setModelConfigClientFactoryForTests(
  factory: (() => ModelConfigClient) | null
): void {
  clientFactory = factory ?? createModelConfigClient;
}

export const useModelConfigStore = defineStore("modelConfig", () => {
  const client = clientFactory();
  const configuration = ref<LlmConfigurationResponse | null>(null);
  const runtimeReport = ref<ConfigCheckReport | null>(null);
  const isLoading = ref(false);
  const isSaving = ref(false);
  const isChecking = ref(false);

  function report(error: unknown): void {
    useFeedbackStore().showError(toUserFacingError(error));
  }

  async function initialize(): Promise<void> {
    isLoading.value = true;
    try {
      configuration.value = await client.getConfiguration();
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isLoading.value = false;
    }
  }

  async function save(request: UpdateLlmConfigurationRequest): Promise<void> {
    isSaving.value = true;
    try {
      configuration.value = await client.updateConfiguration(request);
      useFeedbackStore().show("success", "模型配置已保存并即时生效");
      // 保存后顺手刷新状态面板；刷新失败不影响保存结果。
      await checkRuntime().catch(() => undefined);
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  async function checkRuntime(): Promise<void> {
    isChecking.value = true;
    try {
      runtimeReport.value = await client.checkRuntime();
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isChecking.value = false;
    }
  }

  function reset(): void {
    configuration.value = null;
    runtimeReport.value = null;
    isLoading.value = false;
    isSaving.value = false;
    isChecking.value = false;
  }

  return {
    configuration,
    runtimeReport,
    isLoading,
    isSaving,
    isChecking,
    initialize,
    save,
    checkRuntime,
    reset
  };
});
