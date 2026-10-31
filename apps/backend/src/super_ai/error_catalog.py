"""Shared API and SSE error catalog."""

ERROR_DEFINITIONS = {
    "CHAT_CONTEXT_LIMIT_REACHED": (
        "business",
        409,
        "上下文已达到 95%，请执行手动压缩后再继续对话。",
    ),
    "CHAT_MCP_TOOLS_UNAVAILABLE": (
        "business",
        503,
        "MCP 工具源暂时不可用，本次对话未加载 MCP 工具。",
    ),
    "CHAT_MEMORY_UNAVAILABLE": (
        "business",
        503,
        "会话记忆暂时不可用，本次回答仅基于当前消息。",
    ),
    "AUTH_FORBIDDEN": ("auth", 403, "You do not have permission to access this resource."),
    "AUTH_INVALID_CREDENTIALS": ("auth", 401, "Invalid credentials."),
    "AUTH_PASSWORD_MISMATCH": ("auth", 401, "The current password does not match."),
    "AUTH_SESSION_REVOKED": ("auth", 401, "The authentication session has been revoked."),
    "AUTH_UNAUTHENTICATED": ("auth", 401, "Authentication is required."),
    "BUSINESS_CONFLICT": (
        "business",
        409,
        "The requested operation conflicts with the current resource state.",
    ),
    "BUSINESS_NOT_FOUND": ("business", 404, "The requested resource was not found."),
    "MODEL_CONFIGURATION_INVALID": (
        "validation",
        422,
        "模型配置不合法，已回滚为原配置，请检查后重试。",
    ),
    "VALIDATION_INVALID_ARGUMENT": ("validation", 400, "The request parameters are invalid."),
    "VALIDATION_MISSING_FIELD": ("validation", 422, "A required field is missing."),
    "SYSTEM_INTERNAL_ERROR": ("system", 500, "The system could not complete the request."),
    "SYSTEM_UNAVAILABLE": ("system", 503, "The system is temporarily unavailable."),
}
