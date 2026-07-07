import type { PublicState, StudioBootstrap, SystemLogsResponse, SystemMetricsResponse, SystemStatus } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload?.error === "string" ? payload.error : `HTTP ${response.status}`;
    throw new ApiError(message, response.status);
  }
  return payload as T;
}

export async function apiGet<T>(url: string): Promise<T> {
  const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    throw new ApiError("登录已过期", 401);
  }
  return parseJson<T>(response);
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body ?? {})
  });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    throw new ApiError("登录已过期", 401);
  }
  return parseJson<T>(response);
}

export async function apiPatch<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(body ?? {})
  });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    throw new ApiError("登录已过期", 401);
  }
  return parseJson<T>(response);
}

export async function apiDelete<T>(url: string): Promise<T> {
  const response = await fetch(url, { method: "DELETE" });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    throw new ApiError("登录已过期", 401);
  }
  return parseJson<T>(response);
}

export async function apiUpload<T>(url: string, form: FormData): Promise<T> {
  const response = await fetch(url, { method: "POST", body: form });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    throw new ApiError("登录已过期", 401);
  }
  return parseJson<T>(response);
}

export async function getPublicState(): Promise<PublicState> {
  return apiGet<PublicState>("/api/results.json");
}

export async function getPublicPageState(): Promise<PublicState> {
  const response = await fetch(`./data/results.json?t=${Date.now()}`, { cache: "no-store" });
  return parseJson<PublicState>(response);
}

export async function getSystemStatus(): Promise<SystemStatus> {
  return apiGet<SystemStatus>("/api/system/status");
}

export async function getSystemMetrics(window = "15m"): Promise<SystemMetricsResponse> {
  return apiGet<SystemMetricsResponse>(`/api/system/metrics?window=${encodeURIComponent(window)}`);
}

export async function getSystemLogs(limit = 120): Promise<SystemLogsResponse> {
  return apiGet<SystemLogsResponse>(`/api/system/logs?limit=${limit}`);
}

export async function getBootstrap(): Promise<StudioBootstrap> {
  return apiGet<StudioBootstrap>("/api/studio/bootstrap");
}
