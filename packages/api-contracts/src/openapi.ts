import { API_ERROR_CODES } from "./errors";
import { DOCUMENT_UPLOAD_POLICY } from "./documents";

type HttpMethod = "delete" | "get" | "post" | "put";

interface OpenApiSchema {
  readonly type?: string | readonly string[];
  readonly properties?: Record<string, OpenApiSchema>;
  readonly items?: OpenApiSchema;
  readonly enum?: readonly (string | number | boolean)[];
  readonly required?: readonly string[];
  readonly additionalProperties?: boolean | OpenApiSchema;
  readonly oneOf?: readonly OpenApiSchema[];
  readonly $ref?: string;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly minLength?: number;
  readonly maxLength?: number;
  readonly format?: string;
}

interface OpenApiOperation {
  readonly operationId: string;
  readonly summary: string;
  readonly tags: readonly string[];
  readonly responses: Record<string, { readonly description: string; readonly content?: unknown }>;
  readonly requestBody?: unknown;
  readonly parameters?: readonly unknown[];
  readonly security?: readonly Record<string, readonly string[]>[];
}

interface OpenApiDocument {
  readonly openapi: "3.1.0";
  readonly info: {
    readonly title: string;
    readonly version: string;
  };
  readonly paths: Record<string, Partial<Record<HttpMethod, OpenApiOperation>>>;
  readonly components: {
    readonly schemas: Record<string, OpenApiSchema>;
    readonly securitySchemes: Record<string, unknown>;
  };
}

const jsonContent = (schemaRef: string) => ({
  "application/json": {
    schema: {
      $ref: schemaRef
    }
  }
});

const eventStreamContent = {
  "text/event-stream": {
    schema: {
      $ref: "#/components/schemas/SseEvent"
    }
  }
};

const okResponse = (schemaRef: string) => ({
  description: "Successful response",
  content: jsonContent(schemaRef)
});

const errorResponses = {
  "400": {
    description: API_ERROR_CODES.VALIDATION_INVALID_ARGUMENT.message,
    content: jsonContent("#/components/schemas/ApiErrorResponse")
  },
  "409": {
    description: API_ERROR_CODES.BUSINESS_CONFLICT.message,
    content: jsonContent("#/components/schemas/ApiErrorResponse")
  },
  "500": {
    description: API_ERROR_CODES.SYSTEM_INTERNAL_ERROR.message,
    content: jsonContent("#/components/schemas/ApiErrorResponse")
  }
} as const;

const unauthenticatedResponse = {
  description: API_ERROR_CODES.AUTH_UNAUTHENTICATED.message,
  content: jsonContent("#/components/schemas/ApiErrorResponse")
} as const;

const forbiddenResponse = {
  description: API_ERROR_CODES.AUTH_FORBIDDEN.message,
  content: jsonContent("#/components/schemas/ApiErrorResponse")
} as const;

const protectedErrorResponses = {
  "401": unauthenticatedResponse,
  "403": forbiddenResponse,
  ...errorResponses
} as const;

const bearerSecurity = [{ bearerAuth: [] }] as const;

export const OPENAPI_CONTRACT = {
  openapi: "3.1.0",
  info: {
    title: "Super AI API",
    version: "0.1.0"
  },
  paths: {
    "/health": {
      get: {
        operationId: "getHealth",
        summary: "Read service health",
        tags: ["health"],
        responses: {
          "200": okResponse("#/components/schemas/HealthResponse"),
          ...errorResponses
        }
      }
    },
    "/ready": {
      get: {
        operationId: "getRuntimeReadiness",
        summary: "Check SQLite, Milvus, LLM, and MCP readiness",
        tags: ["health"],
        responses: {
          "200": okResponse("#/components/schemas/RuntimeReadinessResponse"),
          "503": okResponse("#/components/schemas/RuntimeReadinessResponse"),
          ...errorResponses
        }
      }
    },
    "/config/check": {
      get: {
        operationId: "checkRuntimeConfiguration",
        summary: "Diagnose tracked configuration and runtime dependencies safely",
        tags: ["health"],
        responses: {
          "200": okResponse("#/components/schemas/RuntimeConfigurationCheckResponse"),
          "503": okResponse("#/components/schemas/RuntimeConfigurationCheckResponse"),
          ...errorResponses
        }
      }
    },
    "/config/llm": {
      get: {
        operationId: "getLlmConfiguration",
        summary: "Read the current LLM model configuration with masked secrets",
        tags: ["health"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/LlmConfigurationApiResponse"),
          ...protectedErrorResponses
        }
      },
      put: {
        operationId: "updateLlmConfiguration",
        summary: "Update the LLM model configuration and hot-apply it",
        tags: ["health"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/UpdateLlmConfigurationRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/LlmConfigurationApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/auth/profile": {
      put: {
        operationId: "updateUserProfile",
        summary: "Update the current user's display name",
        tags: ["auth"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/UpdateProfileRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/AuthUserApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/auth/password": {
      put: {
        operationId: "changeUserPassword",
        summary: "Change the current user's password and revoke all sessions",
        tags: ["auth"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/ChangePasswordRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/ChangePasswordApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/auth/register": {
      post: {
        operationId: "registerUser",
        summary: "Register a user",
        tags: ["auth"],
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/RegisterRequest")
        },
        responses: {
          "201": okResponse("#/components/schemas/AuthTokenApiResponse"),
          ...errorResponses
        }
      }
    },
    "/auth/login": {
      post: {
        operationId: "loginUser",
        summary: "Log in a user",
        tags: ["auth"],
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/LoginRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/AuthTokenApiResponse"),
          "401": {
            description: API_ERROR_CODES.AUTH_INVALID_CREDENTIALS.message,
            content: jsonContent("#/components/schemas/ApiErrorResponse")
          },
          ...errorResponses
        }
      }
    },
    "/auth/logout": {
      post: {
        operationId: "logoutUser",
        summary: "Log out the current user",
        tags: ["auth"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/LogoutApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/auth/me": {
      get: {
        operationId: "getCurrentUser",
        summary: "Read the current user",
        tags: ["auth"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/AuthUserApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions": {
      get: {
        operationId: "listChatSessions",
        summary: "List chat sessions",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ChatSessionListApiResponse"),
          ...protectedErrorResponses
        }
      },
      post: {
        operationId: "createChatSession",
        summary: "Create a chat session",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/CreateChatSessionRequest")
        },
        responses: {
          "201": okResponse("#/components/schemas/ChatSessionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/configuration": {
      get: {
        operationId: "getChatAssemblyConfiguration",
        summary: "Read the current user's chat prompt and Skill configuration",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ChatAssemblyConfigurationApiResponse"),
          ...protectedErrorResponses
        }
      },
      put: {
        operationId: "updateChatAssemblyConfiguration",
        summary: "Update the current user's chat prompt and Skill configuration",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/UpdateChatAssemblyConfigurationRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/ChatAssemblyConfigurationApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/prompts": {
      post: {
        operationId: "createChatPrompt",
        summary: "Create a user-owned chat system prompt",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/CreateChatPromptRequest")
        },
        responses: {
          "201": okResponse("#/components/schemas/ChatPromptApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/prompts/{promptId}": {
      put: {
        operationId: "updateChatPrompt",
        summary: "Update a user-owned chat system prompt",
        tags: ["chat"],
        security: bearerSecurity,
        parameters: [{ name: "promptId", in: "path", required: true }],
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/UpdateChatPromptRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/ChatPromptApiResponse"),
          ...protectedErrorResponses
        }
      },
      delete: {
        operationId: "deleteChatPrompt",
        summary: "Delete a user-owned chat system prompt",
        tags: ["chat"],
        security: bearerSecurity,
        parameters: [{ name: "promptId", in: "path", required: true }],
        responses: {
          "200": okResponse("#/components/schemas/DeleteChatPromptApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/skills": {
      post: {
        operationId: "uploadChatSkill",
        summary: "Upload a user-owned standard SKILL.md file",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: {
            "multipart/form-data": {
              schema: { $ref: "#/components/schemas/UploadChatSkillRequest" }
            }
          }
        },
        responses: {
          "201": okResponse("#/components/schemas/ChatSkillApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/skills/{skillId}": {
      delete: {
        operationId: "deleteChatSkill",
        summary: "Delete a user-owned Skill file",
        tags: ["chat"],
        security: bearerSecurity,
        parameters: [{ name: "skillId", in: "path", required: true }],
        responses: {
          "200": okResponse("#/components/schemas/DeleteChatSkillApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}": {
      get: {
        operationId: "getChatSession",
        summary: "Read a chat session",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ChatSessionDetailApiResponse"),
          ...protectedErrorResponses
        }
      },
      delete: {
        operationId: "deleteChatSession",
        summary: "Delete a chat session",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/DeleteChatSessionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}/messages": {
      post: {
        operationId: "appendChatMessage",
        summary: "Append a chat message",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/AppendChatMessageRequest")
        },
        responses: {
          "201": okResponse("#/components/schemas/ChatSessionMutationApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}/memory": {
      put: {
        operationId: "updateChatSessionMemory",
        summary: "Update a chat session memory mode",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/UpdateChatMemoryRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/ChatSessionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}/memory:compact": {
      post: {
        operationId: "compactChatSessionMemory",
        summary: "Compact a chat session memory",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ChatSessionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}/tool-call-audits": {
      get: {
        operationId: "listChatToolCallAudits",
        summary: "List chat tool call audits",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ChatToolCallAuditListApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}/messages:clear": {
      post: {
        operationId: "clearChatSessionMessages",
        summary: "Clear chat session messages",
        tags: ["chat"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ClearChatSessionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/chat/sessions/{sessionId}/messages:stream": {
      post: {
        operationId: "streamChatMessage",
        summary: "Stream chat model output",
        tags: ["chat"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/StreamChatMessageRequest")
        },
        responses: {
          "200": {
            description: "SSE stream of chat events",
            content: eventStreamContent
          },
          ...protectedErrorResponses
        }
      }
    },
    "/background-jobs": {
      get: {
        operationId: "listBackgroundJobs",
        summary: "List durable background jobs for the current user",
        tags: ["background-jobs"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/BackgroundJobListApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/background-jobs/{jobId}": {
      get: {
        operationId: "getBackgroundJob",
        summary: "Get one durable background job",
        tags: ["background-jobs"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/BackgroundJobApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/background-jobs/{jobId}:cancel": {
      post: {
        operationId: "cancelBackgroundJob",
        summary: "Request cancellation of a durable background job",
        tags: ["background-jobs"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/BackgroundJobApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/background-jobs/{jobId}:retry": {
      post: {
        operationId: "retryBackgroundJob",
        summary: "Retry a failed or cancelled durable background job",
        tags: ["background-jobs"],
        security: bearerSecurity,
        responses: {
          "202": okResponse("#/components/schemas/BackgroundJobApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/feedback": {
      get: {
        operationId: "listUserFeedback",
        summary: "List current-user feedback for a target",
        tags: ["feedback"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/UserFeedbackListApiResponse"),
          ...protectedErrorResponses
        }
      },
      post: {
        operationId: "upsertUserFeedback",
        summary: "Create or update current-user feedback",
        tags: ["feedback"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/UpsertFeedbackRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/UserFeedbackApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/feedback/{feedbackId}": {
      delete: {
        operationId: "deleteUserFeedback",
        summary: "Delete current-user feedback",
        tags: ["feedback"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/DeleteFeedbackApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/mcp/connections": {
      get: {
        operationId: "listMcpConnections",
        summary: "List managed MCP connections",
        tags: ["mcp"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/McpConnectionListApiResponse"),
          ...protectedErrorResponses
        }
      },
      post: {
        operationId: "createMcpConnection",
        summary: "Create a managed MCP connection",
        tags: ["mcp"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/McpConnectionMutationRequest")
        },
        responses: {
          "201": okResponse("#/components/schemas/McpConnectionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/mcp/connections/{connectionId}": {
      put: {
        operationId: "updateMcpConnection",
        summary: "Update a managed MCP connection",
        tags: ["mcp"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/McpConnectionMutationRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/McpConnectionApiResponse"),
          ...protectedErrorResponses
        }
      },
      delete: {
        operationId: "deleteMcpConnection",
        summary: "Delete a managed MCP connection",
        tags: ["mcp"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/DeleteMcpConnectionApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/mcp/connections/{connectionId}:check": {
      post: {
        operationId: "checkMcpConnection",
        summary: "Check a managed MCP connection and discover tools",
        tags: ["mcp"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/McpConnectionCheckApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/prometheus/sources": {
      get: {
        operationId: "listPrometheusSources",
        summary: "List managed Prometheus data sources",
        tags: ["prometheus"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/PrometheusSourceListApiResponse"),
          ...protectedErrorResponses
        }
      },
      post: {
        operationId: "createPrometheusSource",
        summary: "Create a managed Prometheus data source",
        tags: ["prometheus"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/PrometheusSourceMutationRequest")
        },
        responses: {
          "201": okResponse("#/components/schemas/PrometheusSourceApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/prometheus/sources/{sourceId}": {
      put: {
        operationId: "updatePrometheusSource",
        summary: "Update a managed Prometheus data source",
        tags: ["prometheus"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/PrometheusSourceMutationRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/PrometheusSourceApiResponse"),
          ...protectedErrorResponses
        }
      },
      delete: {
        operationId: "deletePrometheusSource",
        summary: "Delete a managed Prometheus data source",
        tags: ["prometheus"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/DeletePrometheusSourceApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/prometheus/sources/{sourceId}:check": {
      post: {
        operationId: "checkPrometheusSource",
        summary: "Check Prometheus data source connectivity",
        tags: ["prometheus"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/PrometheusSourceCheckApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/prometheus/labels/{label}/values": {
      get: {
        operationId: "listPrometheusLabelValues",
        summary: "List label values from a Prometheus data source",
        tags: ["prometheus"],
        security: bearerSecurity,
        parameters: [
          { name: "label", in: "path", required: true, schema: { type: "string" } },
          { name: "sourceId", in: "query", required: true, schema: { type: "string" } }
        ],
        responses: {
          "200": okResponse("#/components/schemas/PrometheusLabelValuesApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/prometheus/query": {
      post: {
        operationId: "runPrometheusInstantQuery",
        summary: "Run an instant PromQL query against a data source",
        tags: ["prometheus"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/PrometheusQueryRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/PrometheusQueryApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/prometheus/query-range": {
      post: {
        operationId: "runPrometheusRangeQuery",
        summary: "Run a range PromQL query against a data source",
        tags: ["prometheus"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/PrometheusRangeQueryRequest")
        },
        responses: {
          "200": okResponse("#/components/schemas/PrometheusRangeQueryApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases": {
      get: {
        operationId: "listKnowledgeBases",
        summary: "List knowledge bases",
        tags: ["knowledge-bases"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/KnowledgeBaseListResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases/{knowledgeBaseId}/documents": {
      get: {
        operationId: "listKnowledgeDocuments",
        summary: "List knowledge base documents",
        tags: ["knowledge-bases"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/KnowledgeDocumentListApiResponse"),
          ...protectedErrorResponses
        }
      },
      post: {
        operationId: "uploadKnowledgeDocument",
        summary: "Upload a knowledge base document",
        tags: ["knowledge-bases"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          description:
            `multipart/form-data with file and optional overwrite boolean. ` +
            `Max size: ${DOCUMENT_UPLOAD_POLICY.maxSizeBytes} bytes. ` +
            `Allowed documents: Markdown (.md), plain text (.txt) and PDF (.pdf). ` +
            `Markdown and TXT browser MIME variants may be text/markdown, text/plain, empty, or application/octet-stream. ` +
            `PDF MIME should be application/pdf. ` +
            `Duplicate content hash without overwrite returns BUSINESS_CONFLICT; ` +
            `overwrite=true replaces the prior document and its vectors.`,
          content: {
            "multipart/form-data": {
              schema: {
                type: "object",
                required: ["file"],
                properties: {
                  file: { type: "string" },
                  overwrite: { type: "boolean" },
                  chunking: {
                    type: "string"
                  }
                }
              }
            }
          }
        },
        responses: {
          "201": okResponse("#/components/schemas/KnowledgeDocumentUploadApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}": {
      get: {
        operationId: "getKnowledgeDocument",
        summary: "Read knowledge base document metadata",
        tags: ["knowledge-bases"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/KnowledgeDocumentApiResponse"),
          ...protectedErrorResponses
        }
      },
      delete: {
        operationId: "deleteKnowledgeDocument",
        summary: "Delete a knowledge base document",
        tags: ["knowledge-bases"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/KnowledgeDocumentDeleteApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/chunk-preview": {
      get: {
        operationId: "getKnowledgeDocumentChunkPreview",
        summary: "Preview the persisted document chunking result",
        tags: ["knowledge-bases"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/KnowledgeDocumentChunkPreviewApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks": {
      post: {
        operationId: "createDocumentIndexTask",
        summary: "Create a document index task",
        tags: ["index-tasks"],
        security: bearerSecurity,
        responses: {
          "202": okResponse("#/components/schemas/CreateDocumentIndexTaskApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks/{taskId}": {
      get: {
        operationId: "getDocumentIndexTask",
        summary: "Read document index task status",
        tags: ["index-tasks"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/DocumentIndexTaskApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks/{taskId}:retry": {
      post: {
        operationId: "retryDocumentIndexTask",
        summary: "Retry a failed document index task",
        tags: ["index-tasks"],
        security: bearerSecurity,
        responses: {
          "202": okResponse("#/components/schemas/RetryDocumentIndexTaskApiResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/index-tasks": {
      post: {
        operationId: "createIndexTask",
        summary: "Create an index task",
        tags: ["index-tasks"],
        security: bearerSecurity,
        responses: {
          "202": okResponse("#/components/schemas/IndexTaskResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/index-tasks/{taskId}": {
      get: {
        operationId: "getIndexTask",
        summary: "Read index task status",
        tags: ["index-tasks"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/IndexTaskResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/diagnostics": {
      post: {
        operationId: "createAiopsDiagnostic",
        summary: "Create an AIOps diagnostic run",
        tags: ["aiops"],
        security: bearerSecurity,
        requestBody: {
          required: true,
          content: jsonContent("#/components/schemas/CreateAiopsDiagnosticRequest")
        },
        responses: {
          "202": okResponse("#/components/schemas/AiopsDiagnosticResponse"),
          ...protectedErrorResponses
        }
      },
      get: {
        operationId: "listAiopsDiagnostics",
        summary: "List AIOps diagnostic history",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/AiopsDiagnosticHistoryResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/diagnostic-cases": {
      get: {
        operationId: "listAiopsDiagnosticCases",
        summary: "List current user's structured AIOps diagnosis cases",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/AiopsDiagnosticCaseListResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/diagnostic-cases/{caseId}": {
      get: {
        operationId: "getAiopsDiagnosticCase",
        summary: "Get one current user's structured AIOps diagnosis case",
        tags: ["aiops"],
        security: bearerSecurity,
        parameters: [{
          name: "caseId",
          in: "path",
          required: true,
          description: "Structured diagnosis case identifier",
          schema: { type: "string" }
        }],
        responses: {
          "200": okResponse("#/components/schemas/AiopsDiagnosticCase"),
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/alerts/active": {
      get: {
        operationId: "listActiveAiopsAlerts",
        summary: "List current external active alerts",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/ActiveAlertListResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/alerts/stream": {
      get: {
        operationId: "streamActiveAiopsAlerts",
        summary: "Stream the latest active-alert snapshot over SSE",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": {
            description: "SSE stream of active-alert snapshot events",
            content: eventStreamContent
          },
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/diagnostics/{diagnosticId}": {
      get: {
        operationId: "getAiopsDiagnostic",
        summary: "Read AIOps diagnostic status",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/AiopsDiagnosticResponse"),
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/diagnostics/{diagnosticId}:stream": {
      post: {
        operationId: "streamAiopsDiagnostic",
        summary: "Stream AIOps diagnostic events",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": {
            description: "SSE stream of AIOps diagnostic events",
            content: eventStreamContent
          },
          ...protectedErrorResponses
        }
      }
    },
    "/aiops/diagnostics/{diagnosticId}:save-to-knowledge": {
      post: {
        operationId: "confirmAiopsDiagnosticCase",
        summary: "人工确认根因和建议后幂等创建案例与索引任务",
        tags: ["aiops"], security: bearerSecurity,
        requestBody: { required: true, content: jsonContent("#/components/schemas/ConfirmAiopsDiagnosticCaseRequest") },
        responses: { "202": okResponse("#/components/schemas/SaveAiopsDiagnosticCaseResponse"), ...protectedErrorResponses }
      }
    },
    "/aiops/diagnostics/{diagnosticId}/evidence-chain": {
      get: {
        operationId: "getAiopsDiagnosticEvidenceChain",
        summary: "Read complete AIOps diagnostic evidence chain",
        tags: ["aiops"],
        security: bearerSecurity,
        responses: {
          "200": okResponse("#/components/schemas/AiopsDiagnosticEvidenceChainResponse"),
          ...protectedErrorResponses
        }
      }
    }
  },
  components: {
    securitySchemes: {
      bearerAuth: {
        type: "http",
        scheme: "bearer"
      }
    },
    schemas: {
      ApiResponseMeta: {
        type: "object",
        required: ["requestId"],
        properties: {
          requestId: { type: "string" },
          traceId: { type: "string" }
        }
      },
      ApiErrorResponse: {
        type: "object",
        required: ["ok", "error", "meta"],
        properties: {
          ok: { enum: ["false"] },
          error: { $ref: "#/components/schemas/ApiErrorMessage" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ApiErrorMessage: {
        type: "object",
        required: ["code", "category", "httpStatus", "message"],
        properties: {
          code: { type: "string" },
          category: { enum: ["auth", "business", "validation", "system"] },
          httpStatus: { type: "integer" },
          message: { type: "string" },
          details: {
            type: "array",
            items: { $ref: "#/components/schemas/ApiErrorDetail" }
          }
        }
      },
      ApiErrorDetail: {
        type: "object",
        required: ["code", "message"],
        properties: {
          code: { type: "string" },
          message: { type: "string" },
          path: {
            type: "array",
            items: { type: "string" }
          }
        }
      },
      HealthResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["service", "status", "version"],
            properties: {
              service: { type: "string" },
              status: { enum: ["ok"] },
              version: { type: "string" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      RuntimeReadinessResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["status", "dependencies"],
            properties: {
              status: { enum: ["ready", "degraded"] },
              dependencies: { type: "object", additionalProperties: true }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      RuntimeConfigurationCheckResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["status", "configuration", "dependencies"],
            properties: {
              status: { enum: ["ready", "degraded"] },
              configuration: { type: "object", additionalProperties: true },
              dependencies: { type: "object", additionalProperties: true }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      RegisterRequest: {
        type: "object",
        required: ["email", "displayName", "password"],
        properties: {
          email: { type: "string" },
          displayName: { type: "string" },
          password: { type: "string" }
        }
      },
      LoginRequest: {
        type: "object",
        required: ["email", "password"],
        properties: {
          email: { type: "string" },
          password: { type: "string" }
        }
      },
      AuthUser: {
        type: "object",
        required: ["id", "email", "displayName", "createdAt"],
        properties: {
          id: { type: "string" },
          email: { type: "string" },
          displayName: { type: "string" },
          createdAt: { type: "string" }
        }
      },
      AuthTokenResponse: {
        type: "object",
        required: ["user", "accessToken", "tokenType"],
        properties: {
          user: { $ref: "#/components/schemas/AuthUser" },
          accessToken: { type: "string" },
          tokenType: { enum: ["bearer"] }
        }
      },
      AuthTokenApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/AuthTokenResponse" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      AuthUserApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/AuthUser" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      UpdateProfileRequest: {
        type: "object",
        required: ["displayName"],
        properties: {
          displayName: { type: "string" }
        }
      },
      ChangePasswordRequest: {
        type: "object",
        required: ["currentPassword", "newPassword"],
        properties: {
          currentPassword: { type: "string" },
          newPassword: { type: "string" }
        }
      },
      ChangePasswordApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["changed"],
            properties: {
              changed: { enum: ["true"] }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      LlmConfigurationResponse: {
        type: "object",
        required: [
          "provider",
          "apiKeyConfigured",
          "apiKeyLast4",
          "baseUrl",
          "chatModel",
          "contextWindowTokens",
          "embeddingModel",
          "embeddingDimensions",
          "rerankModel",
          "rerankUrl",
          "temperature",
          "timeoutSeconds",
          "maxRetries",
          "langfuseEnabled",
          "langfusePublicKeyConfigured",
          "langfuseSecretKeyConfigured"
        ],
        properties: {
          provider: { enum: ["qwen-openai"] },
          apiKeyConfigured: { type: "boolean" },
          apiKeyLast4: { type: ["string", "null"] },
          baseUrl: { type: "string" },
          chatModel: { type: "string" },
          contextWindowTokens: { type: ["integer", "null"] },
          embeddingModel: { type: "string" },
          embeddingDimensions: { type: "integer" },
          rerankModel: { type: "string" },
          rerankUrl: { type: "string" },
          temperature: { type: "number" },
          timeoutSeconds: { type: "number" },
          maxRetries: { type: "integer" },
          langfuseEnabled: { type: "boolean" },
          langfuseHost: { type: ["string", "null"] },
          langfusePublicKeyConfigured: { type: "boolean" },
          langfusePublicKeyLast4: { type: ["string", "null"] },
          langfuseSecretKeyConfigured: { type: "boolean" },
          langfuseSecretKeyLast4: { type: ["string", "null"] }
        }
      },
      UpdateLlmConfigurationRequest: {
        type: "object",
        required: [
          "baseUrl",
          "chatModel",
          "contextWindowTokens",
          "embeddingModel",
          "embeddingDimensions",
          "rerankModel",
          "rerankUrl",
          "temperature",
          "timeoutSeconds",
          "maxRetries"
        ],
        properties: {
          apiKey: { type: "string" },
          baseUrl: { type: "string" },
          chatModel: { type: "string" },
          contextWindowTokens: { type: "integer" },
          embeddingModel: { type: "string" },
          embeddingDimensions: { type: "integer" },
          rerankModel: { type: "string" },
          rerankUrl: { type: "string" },
          temperature: { type: "number" },
          timeoutSeconds: { type: "number" },
          maxRetries: { type: "integer" },
          langfuseEnabled: { type: "boolean" },
          langfuseHost: { type: "string" },
          langfusePublicKey: { type: "string" },
          langfuseSecretKey: { type: "string" }
        }
      },
      LlmConfigurationApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/LlmConfigurationResponse" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      LogoutApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["revoked"],
            properties: {
              revoked: { enum: ["true"] }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      CreateChatSessionRequest: {
        type: "object",
        properties: {
          title: { type: "string" }
        }
      },
      ChatMessageMetadata: {
        type: "object",
        properties: {
          citations: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: true
            }
          },
          toolCallIds: {
            type: "array",
            items: { type: "string" }
          },
          reasoning: {
            type: "array",
            items: { type: "string" }
          },
          custom: {
            type: "object",
            additionalProperties: true
          }
        },
        additionalProperties: true
      },
      AppendChatMessageRequest: {
        type: "object",
        required: ["role", "content"],
        properties: {
          role: { enum: ["user", "assistant"] },
          content: { type: "string" },
          metadata: { $ref: "#/components/schemas/ChatMessageMetadata" }
        }
      },
      StreamChatMessageRequest: {
        type: "object",
        required: ["content"],
        properties: {
          content: { type: "string" },
          metadata: { $ref: "#/components/schemas/ChatMessageMetadata" }
        }
      },
      UpdateChatMemoryRequest: {
        type: "object",
        required: ["mode"],
        properties: {
          mode: { enum: ["every_30_turns", "context_70_percent", "manual"] }
        }
      },
      ChatPromptAsset: {
        type: "object",
        required: ["id", "label", "content", "isDefault", "createdAt", "updatedAt"],
        properties: {
          id: { type: "string" },
          label: { type: "string" },
          content: { type: "string" },
          isDefault: { type: "boolean" },
          createdAt: { type: "string" },
          updatedAt: { type: "string" }
        }
      },
      ChatSkillAsset: {
        type: "object",
        required: ["id", "filename", "name", "description", "label", "contentPreview", "sizeBytes", "createdAt", "updatedAt"],
        properties: {
          id: { type: "string" },
          filename: { type: "string" },
          name: { type: "string" },
          description: { type: "string" },
          label: { type: "string" },
          contentPreview: { type: "string" },
          sizeBytes: { type: "integer" },
          createdAt: { type: "string" },
          updatedAt: { type: "string" }
        }
      },
      ChatAssemblySelection: {
        type: "object",
        required: ["systemPromptId", "skillIds", "updatedAt"],
        properties: {
          systemPromptId: { type: "string" },
          skillIds: { type: "array", items: { type: "string" } },
          updatedAt: { type: "string" }
        }
      },
      UpdateChatAssemblyConfigurationRequest: {
        type: "object",
        required: ["systemPromptId", "skillIds"],
        properties: {
          systemPromptId: { type: "string" },
          skillIds: { type: "array", items: { type: "string" } }
        }
      },
      CreateChatPromptRequest: {
        type: "object",
        required: ["label", "content"],
        properties: {
          label: { type: "string" },
          content: { type: "string" }
        }
      },
      UpdateChatPromptRequest: {
        type: "object",
        required: ["label", "content"],
        properties: {
          label: { type: "string" },
          content: { type: "string" }
        }
      },
      UploadChatSkillRequest: {
        type: "object",
        required: ["file"],
        properties: {
          file: { type: "string" }
        }
      },
      ChatAssemblyConfiguration: {
        type: "object",
        required: ["prompts", "skills", "selection"],
        properties: {
          prompts: { type: "array", items: { $ref: "#/components/schemas/ChatPromptAsset" } },
          skills: { type: "array", items: { $ref: "#/components/schemas/ChatSkillAsset" } },
          selection: { $ref: "#/components/schemas/ChatAssemblySelection" }
        }
      },
      ChatPromptApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/ChatPromptAsset" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      DeleteChatPromptResponse: {
        type: "object",
        required: ["promptId", "deleted"],
        properties: {
          promptId: { type: "string" },
          deleted: { type: "boolean" }
        }
      },
      DeleteChatPromptApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/DeleteChatPromptResponse" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatSkillApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/ChatSkillAsset" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      DeleteChatSkillResponse: {
        type: "object",
        required: ["skillId", "deleted"],
        properties: {
          skillId: { type: "string" },
          deleted: { type: "boolean" }
        }
      },
      DeleteChatSkillApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/DeleteChatSkillResponse" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatAssemblyConfigurationApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/ChatAssemblyConfiguration" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatSessionResponse: {
        type: "object",
        required: ["id", "ownerUserId", "title", "createdAt", "updatedAt", "memory"],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          title: { type: "string" },
          createdAt: { type: "string" },
          updatedAt: { type: "string" },
          memory: { $ref: "#/components/schemas/ChatMemoryState" }
        }
      },
      ChatMemoryState: {
        type: "object",
        required: [
          "mode",
          "contextTokens",
          "contextWindowTokens",
          "contextUsagePercent",
          "compactedMessageCount",
          "lastCompactedAt",
          "canCompact"
        ],
        properties: {
          mode: { enum: ["every_30_turns", "context_70_percent", "manual"] },
          contextTokens: { type: "integer" },
          contextWindowTokens: { type: "integer" },
          contextUsagePercent: { type: "number" },
          compactedMessageCount: { type: "integer" },
          lastCompactedAt: { type: ["string", "null"] },
          canCompact: { type: "boolean" }
        }
      },
      ChatMessage: {
        type: "object",
        required: ["id", "ownerUserId", "sessionId", "role", "content", "metadata", "createdAt"],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          sessionId: { type: "string" },
          role: { enum: ["user", "assistant"] },
          content: { type: "string" },
          metadata: { $ref: "#/components/schemas/ChatMessageMetadata" },
          createdAt: { type: "string" }
        }
      },
      ChatSessionApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/ChatSessionResponse" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatSessionListApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["items"],
            properties: {
              items: {
                type: "array",
                items: { $ref: "#/components/schemas/ChatSessionResponse" }
              }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatSessionDetailApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["session", "messages"],
            properties: {
              session: { $ref: "#/components/schemas/ChatSessionResponse" },
              messages: {
                type: "array",
                items: { $ref: "#/components/schemas/ChatMessage" }
              }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ToolCallAudit: {
        type: "object",
        required: [
          "id",
          "ownerUserId",
          "sessionId",
          "diagnosticTaskId",
          "toolName",
          "status",
          "arguments",
          "resultSummary",
          "errorMessage",
          "startedAt",
          "completedAt",
          "durationMs",
          "createdAt"
        ],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          sessionId: { type: ["string", "null"] },
          diagnosticTaskId: { type: ["string", "null"] },
          toolName: { type: "string" },
          status: { enum: ["started", "completed", "failed"] },
          arguments: { type: "object", additionalProperties: true },
          resultSummary: { type: ["string", "null"] },
          errorMessage: { type: ["string", "null"] },
          startedAt: { type: "string" },
          completedAt: { type: ["string", "null"] },
          durationMs: { type: ["integer", "null"] },
          createdAt: { type: "string" }
        }
      },
      ChatToolCallAuditListApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["items"],
            properties: {
              items: {
                type: "array",
                items: { $ref: "#/components/schemas/ToolCallAudit" }
              }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatSessionMutationApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["session"],
            properties: {
              session: { $ref: "#/components/schemas/ChatSessionResponse" },
              message: { $ref: "#/components/schemas/ChatMessage" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      ChatStreamCompleteResult: {
        type: "object",
        required: ["session", "message"],
        properties: {
          session: { $ref: "#/components/schemas/ChatSessionResponse" },
          message: { $ref: "#/components/schemas/ChatMessage" }
        }
      },
      ClearChatSessionApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["sessionId", "cleared", "deletedMessages"],
            properties: {
              sessionId: { type: "string" },
              cleared: { enum: ["true"] },
              deletedMessages: { type: "integer" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      DeleteChatSessionApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["sessionId", "deleted"],
            properties: {
              sessionId: { type: "string" },
              deleted: { enum: ["true"] }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      KnowledgeBaseListResponse: {
        type: "object",
        required: ["items"],
        properties: {
          items: {
            type: "array",
            items: { $ref: "#/components/schemas/KnowledgeBaseSummary" }
          }
        }
      },
      KnowledgeBaseSummary: {
        type: "object",
        required: ["id", "name", "ownerUserId"],
        properties: {
          id: { type: "string" },
          name: { type: "string" },
          ownerUserId: { type: "string" }
        }
      },
      KnowledgeDocument: {
        type: "object",
        required: [
          "id",
          "knowledgeBaseId",
          "ownerUserId",
          "filename",
          "sizeBytes",
          "mimeType",
          "contentHash",
          "status",
          "indexStatus",
          "uploadedAt",
          "updatedAt"
        ],
        properties: {
          id: { type: "string" },
          knowledgeBaseId: { type: "string" },
          ownerUserId: { type: "string" },
          filename: { type: "string" },
          sizeBytes: { type: "integer" },
          mimeType: { type: "string" },
          contentHash: { type: "string" },
          status: { enum: ["ready", "deleted"] },
          indexStatus: { enum: ["pending", "indexing", "indexed", "failed"] },
          chunking: { $ref: "#/components/schemas/DocumentChunkingConfiguration" },
          uploadedAt: { type: "string" },
          updatedAt: { type: "string" },
          source: { type: "string" }
        }
      },
      KnowledgeDocumentListApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["items"],
            properties: {
              items: {
                type: "array",
                items: { $ref: "#/components/schemas/KnowledgeDocument" }
              }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      KnowledgeDocumentApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/KnowledgeDocument" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      KnowledgeDocumentUploadApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["document", "duplicateOfDocumentId", "overwrite"],
            properties: {
              document: { $ref: "#/components/schemas/KnowledgeDocument" },
              duplicateOfDocumentId: { type: "string" },
              overwrite: { type: "boolean" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      KnowledgeDocumentDeleteApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["deleted", "documentId"],
            properties: {
              deleted: { enum: ["true"] },
              documentId: { type: "string" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      DocumentChunkingConfiguration: {
        oneOf: [
          {
            type: "object",
            required: ["strategy", "maxCharacters", "overlapCharacters"],
            properties: {
              strategy: { enum: ["fixed-character"] },
              maxCharacters: { type: "integer" },
              overlapCharacters: { type: "integer" }
            }
          },
          {
            type: "object",
            required: ["strategy"],
            properties: {
              strategy: { enum: ["markdown-heading"] }
            }
          },
          {
            type: "object",
            required: ["strategy"],
            properties: {
              strategy: { enum: ["paragraph"] }
            }
          }
        ]
      },
      DocumentChunkPreviewItem: {
        type: "object",
        required: ["index", "characterCount", "excerpt"],
        properties: {
          index: { type: "integer" },
          characterCount: { type: "integer" },
          excerpt: { type: "string" },
          headingPath: { type: "string" }
        }
      },
      DocumentChunkPreview: {
        type: "object",
        required: ["configuration", "totalChunks", "truncated", "items"],
        properties: {
          configuration: { $ref: "#/components/schemas/DocumentChunkingConfiguration" },
          totalChunks: { type: "integer" },
          truncated: { type: "boolean" },
          items: { type: "array", items: { $ref: "#/components/schemas/DocumentChunkPreviewItem" } }
        }
      },
      KnowledgeDocumentChunkPreviewApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["preview"],
            properties: { preview: { $ref: "#/components/schemas/DocumentChunkPreview" } }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      DocumentIndexTask: {
        type: "object",
        required: [
          "id",
          "ownerUserId",
          "knowledgeBaseId",
          "documentId",
          "status",
          "failureReason",
          "retryOfTaskId",
          "createdAt",
          "updatedAt",
          "startedAt",
          "completedAt"
        ],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          knowledgeBaseId: { type: "string" },
          documentId: { type: "string" },
          status: { enum: ["pending", "running", "succeeded", "failed"] },
          failureReason: { type: "string" },
          retryOfTaskId: { type: "string" },
          createdAt: { type: "string" },
          updatedAt: { type: "string" },
          startedAt: { type: "string" },
          completedAt: { type: "string" }
        }
      },
      DocumentIndexTaskApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: { $ref: "#/components/schemas/DocumentIndexTask" },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      CreateDocumentIndexTaskApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["task", "scheduled"],
            properties: {
              task: { $ref: "#/components/schemas/DocumentIndexTask" },
              scheduled: { type: "boolean" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      RetryDocumentIndexTaskApiResponse: {
        type: "object",
        required: ["ok", "data", "meta"],
        properties: {
          ok: { enum: ["true"] },
          data: {
            type: "object",
            required: ["task", "retriedFromTaskId", "scheduled"],
            properties: {
              task: { $ref: "#/components/schemas/DocumentIndexTask" },
              retriedFromTaskId: { type: "string" },
              scheduled: { type: "boolean" }
            }
          },
          meta: { $ref: "#/components/schemas/ApiResponseMeta" }
        }
      },
      KnowledgeRetrievalFilters: {
        type: "object",
        properties: {
          knowledgeBaseIds: {
            type: "array",
            items: { type: "string" }
          },
          documentIds: {
            type: "array",
            items: { type: "string" }
          },
          metadata: {
            type: "object",
            additionalProperties: true
          }
        }
      },
      KnowledgeRetrievalToolInput: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          topK: { type: "integer", minimum: 1, maximum: 5 },
          filters: { $ref: "#/components/schemas/KnowledgeRetrievalFilters" }
        }
      },
      KnowledgeRetrievalHit: {
        type: "object",
        required: [
          "chunkId",
          "documentId",
          "knowledgeBaseId",
          "ownerUserId",
          "tenantId",
          "content",
          "source",
          "metadata",
          "score",
          "vectorRank",
          "bm25Rank",
          "rerankRank",
          "vectorScore",
          "bm25Score",
          "rrfScore",
          "rerankScore"
        ],
        properties: {
          chunkId: { type: "string" },
          documentId: { type: "string" },
          knowledgeBaseId: { type: "string" },
          ownerUserId: { type: "string" },
          tenantId: { type: "string" },
          content: { type: "string" },
          source: { type: "string" },
          metadata: {
            type: "object",
            additionalProperties: true
          },
          score: { type: "number" },
          vectorRank: { type: ["integer", "null"], minimum: 1 },
          bm25Rank: { type: ["integer", "null"], minimum: 1 },
          rerankRank: { type: "integer", minimum: 1 },
          vectorScore: { type: ["number", "null"] },
          bm25Score: { type: ["number", "null"] },
          rrfScore: { type: "number" },
          rerankScore: { type: "number" }
        }
      },
      KnowledgeRetrievalCitationSource: {
        type: "object",
        required: [
          "id",
          "title",
          "sourceType",
          "chunkId",
          "documentId",
          "knowledgeBaseId",
          "source",
          "metadata",
          "score",
          "vectorRank",
          "bm25Rank",
          "rerankRank",
          "vectorScore",
          "bm25Score",
          "rrfScore",
          "rerankScore"
        ],
        properties: {
          id: { type: "string" },
          title: { type: "string" },
          sourceType: { enum: ["knowledge-base"] },
          chunkId: { type: "string" },
          documentId: { type: "string" },
          knowledgeBaseId: { type: "string" },
          source: { type: "string" },
          uri: { type: "string" },
          metadata: {
            type: "object",
            additionalProperties: true
          },
          score: { type: "number" },
          vectorRank: { type: ["integer", "null"], minimum: 1 },
          bm25Rank: { type: ["integer", "null"], minimum: 1 },
          rerankRank: { type: "integer", minimum: 1 },
          vectorScore: { type: ["number", "null"] },
          bm25Score: { type: ["number", "null"] },
          rrfScore: { type: "number" },
          rerankScore: { type: "number" }
        }
      },
      KnowledgeRetrievalToolOutput: {
        type: "object",
        required: ["query", "topK", "results", "citations"],
        properties: {
          query: { type: "string" },
          topK: { type: "integer" },
          results: {
            type: "array",
            items: { $ref: "#/components/schemas/KnowledgeRetrievalHit" }
          },
          citations: {
            type: "array",
            items: { $ref: "#/components/schemas/KnowledgeRetrievalCitationSource" }
          }
        }
      },
      IndexTaskResponse: {
        type: "object",
        properties: {
          id: { type: "string" },
          status: { type: "string" }
        }
      },
      AiopsDiagnosticResponse: {
        type: "object",
        required: [
          "id",
          "ownerUserId",
          "status",
          "query",
          "inputPayload",
          "resultPayload",
          "createdAt",
          "updatedAt",
          "completedAt",
          "reports"
        ],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          status: { enum: ["accepted", "running", "succeeded", "failed"] },
          query: { type: "string" },
          inputPayload: { type: "object", additionalProperties: true },
          resultPayload: { type: "object", additionalProperties: true },
          createdAt: { type: "string" },
          updatedAt: { type: "string" },
          completedAt: { type: ["string", "null"] },
          reports: {
            type: "array",
            items: { $ref: "#/components/schemas/AiopsDiagnosticReport" }
          }
        }
      },
      AiopsDiagnosticHistoryResponse: {
        type: "object",
        required: ["items"],
        properties: {
          items: {
            type: "array",
            items: { $ref: "#/components/schemas/AiopsDiagnosticResponse" }
          }
        }
      },
      AiopsDiagnosticScope: {
        type: "object", additionalProperties: false,
        properties: {
          service: { type: "string", minLength: 1, maxLength: 240 },
          incidentId: { type: "string", minLength: 1, maxLength: 240 },
          traceId: { type: "string", minLength: 1, maxLength: 240 },
          from: { type: "string", format: "date-time" }, to: { type: "string", format: "date-time" }
        }
      },
      AiopsEvidenceCitation: {
        type: "object", additionalProperties: false, required: ["evidenceId", "excerpt"],
        properties: { evidenceId: { type: "string", minLength: 1 }, excerpt: { type: "string", minLength: 1, maxLength: 2000 } }
      },
      AiopsRootCauseHypothesis: {
        type: "object", additionalProperties: false,
        required: ["id", "title", "supportingEvidence", "opposingEvidence"],
        properties: {
          id: { type: "string" }, title: { type: "string" },
          supportingEvidence: { type: "array", items: { $ref: "#/components/schemas/AiopsEvidenceCitation" } },
          opposingEvidence: { type: "array", items: { $ref: "#/components/schemas/AiopsEvidenceCitation" } }
        }
      },
      AiopsStructuredDiagnosis: {
        type: "object", additionalProperties: false,
        required: ["version", "assessment", "summary", "hypotheses", "missingInformation", "recommendations", "verificationSteps"],
        properties: {
          version: { type: "integer", minimum: 1, maximum: 1 },
          assessment: { enum: ["supported", "insufficient_evidence", "conflicting_evidence"] },
          summary: { type: "string" },
          hypotheses: { type: "array", items: { $ref: "#/components/schemas/AiopsRootCauseHypothesis" } },
          missingInformation: { type: "array", items: { type: "string" } },
          recommendations: { type: "array", items: { type: "string" } },
          verificationSteps: { type: "array", items: { type: "string" } }
        }
      },
      ConfirmAiopsDiagnosticCaseRequest: {
        type: "object", additionalProperties: false, required: ["confirmed", "rootCause", "remediation"],
        properties: {
          confirmed: { type: "boolean", enum: [true] },
          rootCause: { type: "string", minLength: 1, maxLength: 4000 },
          remediation: { type: "string", minLength: 1, maxLength: 4000 }
        }
      },
      SaveAiopsDiagnosticCaseResponse: {
        type: "object", required: ["document", "task", "scheduled"],
        properties: {
          document: { $ref: "#/components/schemas/KnowledgeDocument" },
          task: { $ref: "#/components/schemas/DocumentIndexTask" }, scheduled: { type: "boolean" }
        }
      },
      AiopsDiagnosticCase: {
        type: "object",
        required: ["id", "ownerUserId", "taskId", "reportId", "documentId", "indexTaskId", "alertName", "service", "keywords", "rootCause", "remediation", "summary", "evidenceIds", "createdAt"],
        properties: {
          id: { type: "string" }, ownerUserId: { type: "string" }, taskId: { type: "string" }, reportId: { type: "string" }, documentId: { type: "string" }, indexTaskId: { type: "string" }, alertName: { type: "string" }, service: { type: "string" }, reviewStatus: { enum: ["pending", "confirmed"] }, confirmedBy: { type: ["string", "null"] }, confirmedAt: { type: ["string", "null"] }, keywords: { type: "array", items: { type: "string" } }, rootCause: { type: "string" }, remediation: { type: "string" }, summary: { type: "string" }, evidenceIds: { type: "array", items: { type: "string" } }, createdAt: { type: "string" }
        }
      },
      AiopsDiagnosticCaseListResponse: {
        type: "object", required: ["items"], properties: { items: { type: "array", items: { $ref: "#/components/schemas/AiopsDiagnosticCase" } } }
      },
      AiopsDiagnosticEvidenceChainResponse: {
        type: "object",
        required: [
          "task",
          "steps",
          "toolCalls",
          "evidence",
          "reports",
          "reportEvidenceLinks",
          "checkpoints"
        ],
        properties: {
          task: { $ref: "#/components/schemas/AiopsDiagnosticResponse" },
          steps: { type: "array", items: { $ref: "#/components/schemas/AiopsDiagnosticStep" } },
          toolCalls: { type: "array", items: { $ref: "#/components/schemas/ToolCallAudit" } },
          evidence: { type: "array", items: { $ref: "#/components/schemas/AiopsDiagnosticEvidence" } },
          reports: { type: "array", items: { $ref: "#/components/schemas/AiopsDiagnosticReport" } },
          reportEvidenceLinks: {
            type: "array",
            items: { $ref: "#/components/schemas/AiopsReportEvidenceLink" }
          },
          checkpoints: { type: "array", items: { $ref: "#/components/schemas/AiopsGraphCheckpoint" } }
        }
      },
      CreateAiopsDiagnosticRequest: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          alert: { type: "object", additionalProperties: true },
          scope: { $ref: "#/components/schemas/AiopsDiagnosticScope" }
        }
      },
      ActiveAlert: {
        type: "object",
        required: [
          "id",
          "source",
          "alertName",
          "service",
          "severity",
          "status",
          "startsAt",
          "summary",
          "labels",
          "annotations",
          "context"
        ],
        properties: {
          id: { type: "string" },
          source: { type: "string" },
          alertName: { type: "string" },
          service: { type: "string" },
          severity: { type: "string" },
          status: { type: "string" },
          startsAt: { type: "string" },
          summary: { type: "string" },
          labels: { type: "object", additionalProperties: { type: "string" } },
          annotations: { type: "object", additionalProperties: { type: "string" } },
          context: { type: "object", additionalProperties: true },
          diagnosticId: { type: "string" },
          diagnosisStatus: {
            type: "string",
            enum: ["accepted", "running", "succeeded", "failed", "cancelled"]
          }
        }
      },
      ActiveAlertListResponse: {
        type: "object",
        required: ["items"],
        properties: {
          items: { type: "array", items: { $ref: "#/components/schemas/ActiveAlert" } }
        }
      },
      AiopsDiagnosticReport: {
        type: "object",
        required: ["id", "title", "content", "payload", "evidenceIds", "createdAt"],
        properties: {
          id: { type: "string" },
          title: { type: "string" },
          content: { type: "string" },
          payload: { type: "object", additionalProperties: true },
          evidenceIds: { type: "array", items: { type: "string" } },
          diagnosis: { $ref: "#/components/schemas/AiopsStructuredDiagnosis" },
          createdAt: { type: "string" }
        }
      },
      AiopsDiagnosticStep: {
        type: "object",
        required: ["id", "taskId", "sequence", "phase", "status", "payload", "createdAt"],
        properties: {
          id: { type: "string" },
          taskId: { type: "string" },
          sequence: { type: "integer" },
          phase: { type: "string" },
          status: { type: "string" },
          payload: { type: "object", additionalProperties: true },
          createdAt: { type: "string" }
        }
      },
      AiopsDiagnosticEvidence: {
        type: "object",
        required: ["id", "taskId", "stepId", "toolCallId", "kind", "source", "summary", "payload", "createdAt"],
        properties: {
          id: { type: "string" },
          taskId: { type: "string" },
          stepId: { type: ["string", "null"] },
          toolCallId: { type: ["string", "null"] },
          kind: { enum: ["log", "metric", "alert", "ticket", "knowledge_reference"] },
          source: { type: "string" },
          summary: { type: "string" },
          payload: { type: "object", additionalProperties: true },
          createdAt: { type: "string" }
        }
      },
      AiopsReportEvidenceLink: {
        type: "object",
        required: ["id", "taskId", "reportId", "evidenceId", "createdAt"],
        properties: {
          id: { type: "string" },
          taskId: { type: "string" },
          reportId: { type: "string" },
          evidenceId: { type: "string" },
          createdAt: { type: "string" }
        }
      },
      AiopsGraphCheckpoint: {
        type: "object",
        required: ["id", "taskId", "threadId", "checkpointNamespace", "checkpointId", "payload", "metadata", "createdAt"],
        properties: {
          id: { type: "string" },
          taskId: { type: "string" },
          threadId: { type: "string" },
          checkpointNamespace: { type: "string" },
          checkpointId: { type: "string" },
          payload: { type: "object", additionalProperties: true },
          metadata: { type: "object", additionalProperties: true },
          createdAt: { type: "string" }
        }
      },
      BackgroundJob: {
        type: "object",
        required: ["id", "ownerUserId", "kind", "resourceType", "resourceId", "status", "attempt", "maxAttempts", "timeoutSeconds", "availableAt", "createdAt", "updatedAt"],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          kind: { type: "string" },
          resourceType: { type: "string" },
          resourceId: { type: "string" },
          status: { enum: ["queued", "running", "succeeded", "failed", "cancelled"] },
          attempt: { type: "integer", minimum: 0 },
          maxAttempts: { type: "integer", minimum: 1 },
          timeoutSeconds: { type: "integer", minimum: 1 },
          availableAt: { type: "string" },
          cancelRequestedAt: { type: ["string", "null"] },
          retryOfJobId: { type: ["string", "null"] },
          errorMessage: { type: ["string", "null"] },
          createdAt: { type: "string" },
          updatedAt: { type: "string" },
          startedAt: { type: ["string", "null"] },
          completedAt: { type: ["string", "null"] }
        }
      },
      BackgroundJobApiResponse: { type: "object" },
      BackgroundJobListApiResponse: { type: "object" },
      UpsertFeedbackRequest: {
        type: "object",
        required: ["targetType", "targetId", "rating"],
        properties: {
          targetType: { enum: ["chat_message", "citation", "diagnostic_step", "diagnostic_report"] },
          targetId: { type: "string" },
          subjectId: { type: "string" },
          rating: { enum: ["positive", "negative"] },
          reason: { type: "string" },
          comment: { type: "string" },
          correction: { type: "string" }
        }
      },
      UserFeedback: {
        type: "object",
        required: ["id", "ownerUserId", "targetType", "targetId", "rating", "createdAt", "updatedAt"],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          targetType: { enum: ["chat_message", "citation", "diagnostic_step", "diagnostic_report"] },
          targetId: { type: "string" },
          subjectId: { type: ["string", "null"] },
          rating: { enum: ["positive", "negative"] },
          reason: { type: ["string", "null"] },
          comment: { type: ["string", "null"] },
          correction: { type: ["string", "null"] },
          createdAt: { type: "string" },
          updatedAt: { type: "string" }
        }
      },
      UserFeedbackApiResponse: { type: "object" },
      UserFeedbackListApiResponse: { type: "object" },
      DeleteFeedbackApiResponse: { type: "object" },
      McpConnectionMutationRequest: {
        type: "object",
        required: ["name", "transport", "url", "enabled", "timeoutSeconds", "retries"],
        properties: {
          name: { type: "string" },
          transport: { enum: ["sse", "streamable_http"] },
          url: { type: "string" },
          enabled: { type: "boolean" },
          timeoutSeconds: { type: "integer", minimum: 1, maximum: 300 },
          retries: { type: "integer", minimum: 0, maximum: 5 }
        }
      },
      McpToolSummary: {
        type: "object",
        required: ["name", "description", "inputSchema", "serverName"],
        properties: {
          name: { type: "string" },
          description: { type: "string" },
          inputSchema: { type: "object", additionalProperties: true },
          serverName: { type: "string" }
        }
      },
      McpConnection: {
        type: "object",
        required: ["id", "ownerUserId", "name", "transport", "url", "enabled", "timeoutSeconds", "retries", "createdAt", "updatedAt"],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          name: { type: "string" },
          transport: { enum: ["sse", "streamable_http"] },
          url: { type: "string" },
          enabled: { type: "boolean" },
          timeoutSeconds: { type: "integer" },
          retries: { type: "integer" },
          lastCheck: { type: ["object", "null"], additionalProperties: true },
          createdAt: { type: "string" },
          updatedAt: { type: "string" }
        }
      },
      McpConnectionApiResponse: { type: "object" },
      McpConnectionListApiResponse: { type: "object" },
      McpConnectionCheckApiResponse: { type: "object" },
      DeleteMcpConnectionApiResponse: { type: "object" },
      PrometheusSourceMutationRequest: {
        type: "object",
        required: ["name", "baseUrl"],
        properties: {
          name: { type: "string" },
          baseUrl: { type: "string" },
          username: { type: "string" },
          password: { type: "string" },
          enabled: { type: "boolean" },
          timeoutSeconds: { type: "integer", minimum: 1, maximum: 300 },
          maxSeries: { type: "integer", minimum: 1, maximum: 100 }
        }
      },
      PrometheusSourceCheck: {
        type: "object",
        required: ["ok", "error", "checkedAt"],
        properties: {
          ok: { type: "boolean" },
          error: { type: ["string", "null"] },
          checkedAt: { type: ["string", "null"] }
        }
      },
      PrometheusSource: {
        type: "object",
        required: ["id", "ownerUserId", "name", "baseUrl", "username", "enabled", "timeoutSeconds", "maxSeries", "lastCheck", "createdAt", "updatedAt"],
        properties: {
          id: { type: "string" },
          ownerUserId: { type: "string" },
          name: { type: "string" },
          baseUrl: { type: "string" },
          username: { type: ["string", "null"] },
          enabled: { type: "boolean" },
          timeoutSeconds: { type: "integer" },
          maxSeries: { type: "integer" },
          lastCheck: { type: ["object", "null"], additionalProperties: true },
          createdAt: { type: "string" },
          updatedAt: { type: "string" }
        }
      },
      PrometheusSourceApiResponse: { type: "object" },
      PrometheusSourceListApiResponse: { type: "object" },
      PrometheusSourceCheckApiResponse: { type: "object" },
      DeletePrometheusSourceApiResponse: { type: "object" },
      PrometheusSeriesPoint: {
        type: "object",
        required: ["timestamp", "value"],
        properties: {
          timestamp: { type: "number" },
          value: { type: "number" }
        }
      },
      PrometheusSeries: {
        type: "object",
        required: ["metric", "points"],
        properties: {
          metric: { type: "object", additionalProperties: { type: "string" } },
          points: { type: "array", items: { $ref: "#/components/schemas/PrometheusSeriesPoint" } }
        }
      },
      PrometheusLabelValuesApiResponse: { type: "object" },
      PrometheusQueryRequest: {
        type: "object",
        required: ["sourceId", "query"],
        properties: {
          sourceId: { type: "string" },
          query: { type: "string" },
          timeMs: { type: "number" }
        }
      },
      PrometheusQueryApiResponse: { type: "object" },
      PrometheusRangeQueryRequest: {
        type: "object",
        required: ["sourceId", "query", "startMs", "endMs", "stepSeconds"],
        properties: {
          sourceId: { type: "string" },
          query: { type: "string" },
          startMs: { type: "number" },
          endMs: { type: "number" },
          stepSeconds: { type: "integer", minimum: 5, maximum: 300 }
        }
      },
      PrometheusRangeQueryApiResponse: { type: "object" },
      SseEvent: {
        oneOf: [
          { $ref: "#/components/schemas/ContentDeltaEvent" },
          { $ref: "#/components/schemas/ReasoningDeltaEvent" },
          { $ref: "#/components/schemas/ToolCallEvent" },
          { $ref: "#/components/schemas/ReferenceSourceEvent" },
          { $ref: "#/components/schemas/TaskStatusEvent" },
          { $ref: "#/components/schemas/ReportEvent" },
          { $ref: "#/components/schemas/CompleteEvent" },
          { $ref: "#/components/schemas/ErrorEvent" },
          { $ref: "#/components/schemas/NoticeEvent" },
          { $ref: "#/components/schemas/AlertsSnapshotEvent" }
        ]
      },
      ContentDeltaEvent: { type: "object" },
      ReasoningDeltaEvent: { type: "object" },
      ToolCallEvent: { type: "object" },
      ReferenceSourceEvent: {
        type: "object",
        properties: {
          reference: {
            type: "object",
            required: ["id", "title", "sourceType"],
            properties: {
              id: { type: "string" },
              title: { type: "string" },
              sourceType: { enum: ["knowledge-base", "log", "metric", "document", "url"] },
              chunkId: { type: "string" },
              documentId: { type: "string" },
              knowledgeBaseId: { type: "string" },
              source: { type: "string" },
              uri: { type: "string" },
              metadata: {
                type: "object",
                additionalProperties: true
              },
              score: { type: "number" },
              vectorRank: { type: "integer", minimum: 1 },
              bm25Rank: { type: "integer", minimum: 1 },
              rerankRank: { type: "integer", minimum: 1 },
              vectorScore: { type: "number" },
              bm25Score: { type: "number" },
              rrfScore: { type: "number" },
              rerankScore: { type: "number" },
              excerpt: { type: "string" },
              knowledgeType: { enum: ["document", "sop", "diagnostic-case"] }
            }
          }
        }
      },
      TaskStatusEvent: { type: "object" },
      ReportEvent: {
        type: "object", required: ["id", "type", "channel", "timestamp", "report"],
        properties: {
          id: { type: "string" }, type: { enum: ["report"] }, channel: { enum: ["aiops", "chat"] }, timestamp: { type: "string" },
          report: { type: "object", required: ["id", "title", "content"], properties: {
            id: { type: "string" }, title: { type: "string" }, content: { type: "string" },
            evidenceIds: { type: "array", items: { type: "string" } },
            diagnosis: { $ref: "#/components/schemas/AiopsStructuredDiagnosis" }
          } }
        }
      },
      CompleteEvent: { type: "object" },
      ErrorEvent: {
        type: "object",
        properties: {
          error: { $ref: "#/components/schemas/ApiErrorMessage" }
        }
      },
      NoticeEvent: {
        type: "object",
        required: ["id", "type", "channel", "timestamp", "notice"],
        properties: {
          id: { type: "string" },
          type: { enum: ["notice"] },
          channel: { enum: ["chat"] },
          timestamp: { type: "string" },
          notice: {
            type: "object",
            required: ["code", "message"],
            properties: {
              code: { type: "string" },
              message: { type: "string" }
            }
          }
        }
      },
      AlertsSnapshotEvent: {
        type: "object",
        required: ["id", "type", "channel", "timestamp", "items"],
        properties: {
          id: { type: "string" },
          type: { enum: ["alerts.snapshot"] },
          channel: { enum: ["aiops"] },
          timestamp: { type: "string" },
          items: { type: "array", items: { $ref: "#/components/schemas/ActiveAlert" } }
        }
      }
    }
  }
} as const satisfies OpenApiDocument;
