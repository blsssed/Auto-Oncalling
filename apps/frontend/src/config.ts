declare const __PUBLIC_API_BASE_URL__: string;
export function resolveApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, "");
}
export const API_BASE_URL = resolveApiBaseUrl(__PUBLIC_API_BASE_URL__);
