import type {
  LlmConfigurationResponse,
  UpdateLlmConfigurationRequest
} from "@agent-py/api-contracts";

import { createApiClient, type ApiClientOptions } from "../api/apiClient";
import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { API_BASE_URL } from "../config";

/** /config/check 的单段结果：配置段用 valid，依赖探测段用 ok；均只含非敏感元数据。 */
export interface ConfigCheckComponent {
  readonly valid?: boolean;
  readonly ok?: boolean;
  readonly provider?: string | null;
  readonly model?: string | null;
  readonly baseUrl?: string;
  readonly engine?: string;
  readonly uri?: string;
  readonly endpoint?: string;
  readonly latencyMs?: number;
  readonly error?: string | null;
}

export interface ConfigCheckReport {
  readonly status: string;
  readonly configuration: Readonly<Record<string, ConfigCheckComponent>>;
  readonly dependencies: Readonly<Record<string, ConfigCheckComponent>>;
}

export interface ModelConfigClient {
  getConfiguration(): Promise<LlmConfigurationResponse>;
  updateConfiguration(request: UpdateLlmConfigurationRequest): Promise<LlmConfigurationResponse>;
  checkRuntime(): Promise<ConfigCheckReport>;
}

export function createModelConfigClient(options: Partial<ApiClientOptions> = {}): ModelConfigClient {
  const api = createApiClient({
    baseUrl: options.baseUrl ?? API_BASE_URL,
    ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
    getAccessToken: options.getAccessToken ?? (() => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY))
  });
  return {
    getConfiguration: () => api.request<LlmConfigurationResponse>("/config/llm"),
    updateConfiguration: (request) =>
      api.request<LlmConfigurationResponse>("/config/llm", {
        method: "PUT",
        body: JSON.stringify(request)
      }),
    checkRuntime: () => api.request<ConfigCheckReport>("/config/check")
  };
}
