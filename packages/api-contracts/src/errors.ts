export type ApiErrorCategory = "auth" | "business" | "validation" | "system";

export interface ApiErrorCodeDefinition {
  readonly category: ApiErrorCategory;
  readonly httpStatus: number;
  readonly message: string;
}

export const API_ERROR_CODES = {
  CHAT_CONTEXT_LIMIT_REACHED: {
    category: "business",
    httpStatus: 409,
    message: "上下文已达到 95%，请执行手动压缩后再继续对话。"
  },
  CHAT_MCP_TOOLS_UNAVAILABLE: {
    category: "business",
    httpStatus: 503,
    message: "MCP 工具源暂时不可用，本次对话未加载 MCP 工具。"
  },
  CHAT_MEMORY_UNAVAILABLE: {
    category: "business",
    httpStatus: 503,
    message: "会话记忆暂时不可用，本次回答仅基于当前消息。"
  },
  AUTH_INVALID_CREDENTIALS: {
    category: "auth",
    httpStatus: 401,
    message: "Invalid credentials."
  },
  AUTH_PASSWORD_MISMATCH: {
    category: "auth",
    httpStatus: 401,
    message: "The current password does not match."
  },
  AUTH_FORBIDDEN: {
    category: "auth",
    httpStatus: 403,
    message: "You do not have permission to access this resource."
  },
  AUTH_SESSION_REVOKED: {
    category: "auth",
    httpStatus: 401,
    message: "The authentication session has been revoked."
  },
  AUTH_UNAUTHENTICATED: {
    category: "auth",
    httpStatus: 401,
    message: "Authentication is required."
  },
  BUSINESS_CONFLICT: {
    category: "business",
    httpStatus: 409,
    message: "The requested operation conflicts with the current resource state."
  },
  BUSINESS_NOT_FOUND: {
    category: "business",
    httpStatus: 404,
    message: "The requested resource was not found."
  },
  MODEL_CONFIGURATION_INVALID: {
    category: "validation",
    httpStatus: 422,
    message: "模型配置不合法，已回滚为原配置，请检查后重试。"
  },
  VALIDATION_INVALID_ARGUMENT: {
    category: "validation",
    httpStatus: 400,
    message: "The request parameters are invalid."
  },
  VALIDATION_MISSING_FIELD: {
    category: "validation",
    httpStatus: 422,
    message: "A required field is missing."
  },
  SYSTEM_INTERNAL_ERROR: {
    category: "system",
    httpStatus: 500,
    message: "The system could not complete the request."
  },
  SYSTEM_UNAVAILABLE: {
    category: "system",
    httpStatus: 503,
    message: "The system is temporarily unavailable."
  }
} as const satisfies Record<string, ApiErrorCodeDefinition>;

export type ApiErrorCode = keyof typeof API_ERROR_CODES;
