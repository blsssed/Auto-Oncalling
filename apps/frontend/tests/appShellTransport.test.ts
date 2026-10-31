import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "../src/api/apiClient";
import { createSseClient } from "../src/api/sseClient";

describe("application transport", () => {
  it("attaches the bearer token and unwraps the shared success envelope", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: { id: "kb_user_1" },
          meta: { requestId: "req_1" }
        }),
        { headers: { "Content-Type": "application/json" }, status: 200 }
      )
    );
    const client = createApiClient({
      baseUrl: "http://api.test",
      fetchImpl,
      getAccessToken: () => "token_1"
    });

    await expect(client.request<{ id: string }>("/knowledge-bases")).resolves.toEqual({
      id: "kb_user_1"
    });
    const request = fetchImpl.mock.calls[0];
    expect(request?.[0]).toBe("http://api.test/knowledge-bases");
    expect(new Headers(request?.[1]?.headers).get("Authorization")).toBe("Bearer token_1");
  });

  it("normalizes a malformed backend error body into a safe frontend error", async () => {
    const client = createApiClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response("upstream exploded", { status: 502 })
      ),
      getAccessToken: () => null
    });

    await expect(client.request("/health")).rejects.toMatchObject({
      message: "后端服务暂时不可用（HTTP 502），请查看 apps/backend/var/backend-local.log 后重试。",
      status: 502
    });
  });

  it("explains the backend address when fetch fails at the connection layer", async () => {
    const client = createApiClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")),
      getAccessToken: () => null
    });

    await expect(client.request("/auth/login", { method: "POST" })).rejects.toMatchObject({
      message: "无法连接后端服务（http://api.test）。请确认后端已启动；本机日志见 apps/backend/var/backend-local.log。",
      status: 0
    });
  });

  it("explains the backend address when an SSE stream cannot connect", async () => {
    const sse = createSseClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")),
      getAccessToken: () => null
    });

    await expect(async () => {
      for await (const _event of sse.stream("/aiops/alerts/stream", { method: "GET" })) {
        // 不应到达：连接层直接失败。
      }
    }).rejects.toMatchObject({
      message: "无法连接后端服务（http://api.test）。请确认后端已启动；本机日志见 apps/backend/var/backend-local.log。"
    });
  });

  it("parses chunked SSE frames as the shared event union", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"id":"evt_1","type":"content.delta","channel":"chat",'
          )
        );
        controller.enqueue(encoder.encode('"timestamp":"2026-07-10T00:00:00Z","delta":"Hi","sequence":1}\n\n'));
        controller.close();
      }
    });
    const sse = createSseClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(body, { headers: { "Content-Type": "text/event-stream" }, status: 200 })
      ),
      getAccessToken: () => "token_1"
    });
    const events = [];

    for await (const event of sse.stream("/chat/sessions/session_1/messages:stream", {
      body: JSON.stringify({ content: "Hello" }),
      method: "POST"
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      expect.objectContaining({ delta: "Hi", type: "content.delta" })
    ]);
  });

  it("cancels the underlying stream when the consumer stops early", async () => {
    const encoder = new TextEncoder();
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        // 先推一条完整事件，然后保持打开：模拟长期 SSE 连接。
        controller.enqueue(
          encoder.encode(
            'data: {"id":"evt_1","type":"alerts.snapshot","channel":"aiops","timestamp":"2026-07-10T00:00:00Z","items":[]}\n\n'
          )
        );
      },
      cancel() {
        cancelled = true;
      }
    });
    const sse = createSseClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(body, { headers: { "Content-Type": "text/event-stream" }, status: 200 })
      ),
      getAccessToken: () => "token_1"
    });

    for await (const event of sse.stream("/aiops/alerts/stream", { method: "GET" })) {
      expect(event.type).toBe("alerts.snapshot");
      break;
    }
    // reader.cancel() 是异步收尾：给微任务一个执行机会。
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(cancelled).toBe(true);
  });
});
