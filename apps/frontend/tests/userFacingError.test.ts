import { describe, expect, it } from "vitest";

import { toUserFacingError } from "../src/ui/userFacingError";

describe("user facing error mapping", () => {
  it("maps chat optional-dependency codes to Chinese degrade notices", () => {
    expect(
      toUserFacingError({
        error: {
          code: "CHAT_MCP_TOOLS_UNAVAILABLE",
          category: "business",
          httpStatus: 503,
          message: "MCP 工具源暂时不可用，本次对话未加载 MCP 工具。"
        }
      })
    ).toBe("MCP 工具源暂时不可用，本次对话未加载 MCP 工具。");
    expect(
      toUserFacingError({
        error: {
          code: "CHAT_MEMORY_UNAVAILABLE",
          category: "business",
          httpStatus: 503,
          message: "The system is temporarily unavailable."
        }
      })
    ).toBe("会话记忆暂时不可用，本次回答仅基于当前消息。");
  });

  it("passes through specific transport-level Chinese details for unknown codes", () => {
    expect(
      toUserFacingError({
        error: {
          code: "SYSTEM_UNAVAILABLE",
          category: "system",
          httpStatus: 503,
          message: "无法连接后端服务（http://127.0.0.1:8000）。请确认后端已启动。"
        }
      })
    ).toBe("无法连接后端服务（http://127.0.0.1:8000）。请确认后端已启动。");
  });
});
