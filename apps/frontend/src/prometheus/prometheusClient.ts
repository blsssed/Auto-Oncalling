import type {
  DeletePrometheusSourceResponse,
  PrometheusLabelValuesResponse,
  PrometheusQueryRequest,
  PrometheusQueryResponse,
  PrometheusRangeQueryRequest,
  PrometheusRangeQueryResponse,
  PrometheusSource,
  PrometheusSourceCheckResponse,
  PrometheusSourceListResponse,
  PrometheusSourceMutationRequest
} from "@agent-py/api-contracts";

import { createApiClient } from "../api/apiClient";
import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { API_BASE_URL } from "../config";

export interface PrometheusClient {
  check(sourceId: string): Promise<PrometheusSourceCheckResponse>;
  create(request: PrometheusSourceMutationRequest): Promise<PrometheusSource>;
  delete(sourceId: string): Promise<DeletePrometheusSourceResponse>;
  labelValues(sourceId: string, label: string): Promise<PrometheusLabelValuesResponse>;
  list(): Promise<PrometheusSourceListResponse>;
  query(request: PrometheusQueryRequest): Promise<PrometheusQueryResponse>;
  queryRange(request: PrometheusRangeQueryRequest): Promise<PrometheusRangeQueryResponse>;
  update(sourceId: string, request: PrometheusSourceMutationRequest): Promise<PrometheusSource>;
}

export function createPrometheusClient(): PrometheusClient {
  const api = createApiClient({
    baseUrl: API_BASE_URL,
    getAccessToken: () => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
  });
  return {
    check: (sourceId) =>
      api.request<PrometheusSourceCheckResponse>(`/prometheus/sources/${sourceId}:check`, {
        method: "POST"
      }),
    create: (request) =>
      api.request<PrometheusSource>("/prometheus/sources", {
        body: JSON.stringify(request),
        method: "POST"
      }),
    delete: (sourceId) =>
      api.request<DeletePrometheusSourceResponse>(`/prometheus/sources/${sourceId}`, {
        method: "DELETE"
      }),
    labelValues: (sourceId, label) =>
      api.request<PrometheusLabelValuesResponse>(
        `/prometheus/labels/${encodeURIComponent(label)}/values?sourceId=${encodeURIComponent(sourceId)}`,
        { method: "GET" }
      ),
    list: () => api.request<PrometheusSourceListResponse>("/prometheus/sources"),
    query: (request) =>
      api.request<PrometheusQueryResponse>("/prometheus/query", {
        body: JSON.stringify(request),
        method: "POST"
      }),
    queryRange: (request) =>
      api.request<PrometheusRangeQueryResponse>("/prometheus/query-range", {
        body: JSON.stringify(request),
        method: "POST"
      }),
    update: (sourceId, request) =>
      api.request<PrometheusSource>(`/prometheus/sources/${sourceId}`, {
        body: JSON.stringify(request),
        method: "PUT"
      })
  };
}
