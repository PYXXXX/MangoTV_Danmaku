import type { PublicState, StudioBootstrap, SystemLogsResponse, SystemStatus } from "./types";

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

export async function getSystemLogs(limit = 120): Promise<SystemLogsResponse> {
  return apiGet<SystemLogsResponse>(`/api/system/logs?limit=${limit}`);
}

export async function getBootstrap(): Promise<StudioBootstrap> {
  const [publicState, systemStatus, logs] = await Promise.all([
    getPublicState(),
    getSystemStatus().catch(() => undefined),
    getSystemLogs(40).then((payload) => payload.events ?? payload.items ?? []).catch(() => [])
  ]);
  return {
    generatedAt: new Date().toISOString(),
    publicState,
    systemStatus,
    logs
  };
}
