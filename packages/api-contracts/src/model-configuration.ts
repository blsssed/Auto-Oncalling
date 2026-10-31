export interface LlmConfigurationResponse {
  readonly provider: "qwen-openai";
  readonly apiKeyConfigured: boolean;
  readonly apiKeyLast4: string | null;
  readonly baseUrl: string;
  readonly chatModel: string;
  readonly contextWindowTokens: number | null;
  readonly embeddingModel: string;
  readonly embeddingDimensions: number;
  readonly rerankModel: string;
  readonly rerankUrl: string;
  readonly temperature: number;
  readonly timeoutSeconds: number;
  readonly maxRetries: number;
  readonly langfuseEnabled: boolean;
  readonly langfuseHost: string | null;
  readonly langfusePublicKeyConfigured: boolean;
  readonly langfusePublicKeyLast4: string | null;
  readonly langfuseSecretKeyConfigured: boolean;
  readonly langfuseSecretKeyLast4: string | null;
}

export interface UpdateLlmConfigurationRequest {
  readonly apiKey?: string;
  readonly baseUrl: string;
  readonly chatModel: string;
  readonly contextWindowTokens: number;
  readonly embeddingModel: string;
  readonly embeddingDimensions: number;
  readonly rerankModel: string;
  readonly rerankUrl: string;
  readonly temperature: number;
  readonly timeoutSeconds: number;
  readonly maxRetries: number;
  readonly langfuseEnabled?: boolean;
  readonly langfuseHost?: string;
  readonly langfusePublicKey?: string;
  readonly langfuseSecretKey?: string;
}
