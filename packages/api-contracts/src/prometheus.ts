export interface PrometheusSourceCheck {
  readonly ok: boolean;
  readonly error: string | null;
  readonly checkedAt: string | null;
}

export interface PrometheusSource {
  readonly id: string;
  readonly ownerUserId: string;
  readonly name: string;
  readonly baseUrl: string;
  readonly username: string | null;
  readonly enabled: boolean;
  readonly timeoutSeconds: number;
  readonly maxSeries: number;
  readonly lastCheck: PrometheusSourceCheck | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface PrometheusSourceMutationRequest {
  readonly name: string;
  readonly baseUrl: string;
  readonly username?: string;
  readonly password?: string;
  readonly enabled?: boolean;
  readonly timeoutSeconds?: number;
  readonly maxSeries?: number;
}

export interface PrometheusSourceListResponse {
  readonly items: readonly PrometheusSource[];
}

export interface PrometheusSourceCheckResponse {
  readonly source: PrometheusSource;
  readonly check: PrometheusSourceCheck;
}

export interface DeletePrometheusSourceResponse {
  readonly deleted: true;
  readonly sourceId: string;
}

export interface PrometheusSeriesPoint {
  readonly timestamp: number;
  readonly value: number;
}

export interface PrometheusSeries {
  readonly metric: Readonly<Record<string, string>>;
  readonly points: readonly PrometheusSeriesPoint[];
}

export interface PrometheusLabelValuesResponse {
  readonly label: string;
  readonly values: readonly string[];
}

export interface PrometheusQueryRequest {
  readonly sourceId: string;
  readonly query: string;
  readonly timeMs?: number;
}

export interface PrometheusQueryResponse {
  readonly query: string;
  readonly series: readonly PrometheusSeries[];
}

export interface PrometheusRangeQueryRequest {
  readonly sourceId: string;
  readonly query: string;
  readonly startMs: number;
  readonly endMs: number;
  readonly stepSeconds: number;
}

export interface PrometheusRangeQueryResponse {
  readonly query: string;
  readonly startMs: number;
  readonly endMs: number;
  readonly stepSeconds: number;
  readonly series: readonly PrometheusSeries[];
}
