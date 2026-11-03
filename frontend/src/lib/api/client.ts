import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import { API_BASE_URL, REQUEST_TIMEOUT_MS } from "@/lib/constants/config";
import type { ApiEnvelope, ApiErrorPayload } from "@/types/api";

/**
 * The single Axios instance for the whole app.
 *
 * Responsibilities, all in one place:
 *  - base URL + credentials (the refresh token lives in an HttpOnly cookie)
 *  - attaching the access token
 *  - a correlation id on every request
 *  - unwrapping the backend's `{success, data, meta}` envelope
 *  - normalising every failure into one `ApiError` shape
 *  - refreshing a expired access token once, and replaying queued requests
 *
 * No component ever calls `fetch` or constructs a URL itself.
 */

let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;
  readonly requestId?: string;

  constructor(payload: {
    code: string;
    message: string;
    status: number;
    details?: Record<string, unknown>;
    requestId?: string;
  }) {
    super(payload.message);
    this.name = "ApiError";
    this.code = payload.code;
    this.status = payload.status;
    this.details = payload.details;
    this.requestId = payload.requestId;
  }

  /** Permission and scope failures are actionable; the UI treats them differently. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** True when retrying could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status >= 500 || this.status === 429 || this.status === 0;
  }
}

function correlationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "69420",
  },
});

// --------------------------------------------------------------------------- //
// Request: auth + correlation
// --------------------------------------------------------------------------- //
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (accessToken) {
    config.headers.set("Authorization", `Bearer ${accessToken}`);
  }
  config.headers.set("X-Request-ID", correlationId());
  config.headers.set("ngrok-skip-browser-warning", "69420");
  return config;
});

// --------------------------------------------------------------------------- //
// Response: refresh-once, then normalise errors
// --------------------------------------------------------------------------- //
type RetriableConfig = AxiosRequestConfig & { _retried?: boolean };

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  // Deliberately a bare axios call: going through `api` would recurse through
  // this very interceptor.
  try {
    const response = await axios.post<ApiEnvelope<{ tokens: { access_token: string } }>>(
      `${API_BASE_URL}/auth/refresh`,
      {},
      {
        withCredentials: true,
        timeout: REQUEST_TIMEOUT_MS,
        headers: { "ngrok-skip-browser-warning": "69420" },
      },
    );
    const token = response.data?.data?.tokens?.access_token ?? null;
    setAccessToken(token);
    return token;
  } catch {
    setAccessToken(null);
    return null;
  }
}

/**
 * Force a fresh access token, sharing one in-flight request across callers.
 *
 * Exported because not every consumer of the token is an HTTP request. The
 * inventory websocket authenticates with the token in its query string, and a
 * rejected handshake never produces a 401 for the response interceptor below to
 * catch - so without this, an expired token leaves the socket retrying the same
 * dead credential forever.
 */
export async function ensureFreshAccessToken(): Promise<string | null> {
  refreshPromise ??= refreshAccessToken().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

function toApiError(error: AxiosError<ApiErrorPayload>): ApiError {
  const status = error.response?.status ?? 0;
  const payload = error.response?.data;

  if (payload?.error) {
    return new ApiError({
      code: payload.error.code,
      message: payload.error.message,
      status,
      details: payload.error.details,
      requestId: payload.request_id ?? undefined,
    });
  }

  if (error.code === "ECONNABORTED") {
    return new ApiError({
      code: "TIMEOUT",
      message: "The request took too long. Please try again.",
      status: 0,
    });
  }

  if (!error.response) {
    return new ApiError({
      code: "NETWORK_ERROR",
      message:
        "Could not reach the API. Check that the backend is running on " + API_BASE_URL + ".",
      status: 0,
    });
  }

  return new ApiError({
    code: "HTTP_ERROR",
    message: error.message || "Something went wrong.",
    status,
  });
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorPayload>) => {
    const config = error.config as RetriableConfig | undefined;
    const status = error.response?.status;
    const isAuthRoute = Boolean(config?.url?.includes("/auth/"));

    // One refresh attempt, shared across concurrent 401s so we never stampede.
    if (status === 401 && config && !config._retried && !isAuthRoute) {
      config._retried = true;
      const token = await ensureFreshAccessToken();

      if (token) {
        config.headers = { ...config.headers, Authorization: `Bearer ${token}` };
        return api.request(config);
      }
      onUnauthorized?.();
    }

    return Promise.reject(toApiError(error));
  },
);

// --------------------------------------------------------------------------- //
// Envelope helpers - every call site gets `data`, never the envelope
// --------------------------------------------------------------------------- //
export async function apiGet<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await api.get<ApiEnvelope<T>>(url, config);
  return unwrap(response.data);
}

export async function apiPost<T>(
  url: string,
  body?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await api.post<ApiEnvelope<T>>(url, body ?? {}, config);
  return unwrap(response.data);
}

export async function apiPatch<T>(
  url: string,
  body?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await api.patch<ApiEnvelope<T>>(url, body ?? {}, config);
  return unwrap(response.data);
}

export async function apiDelete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await api.delete<ApiEnvelope<T>>(url, config);
  return unwrap(response.data);
}

/** Same as apiGet but keeps `meta` - used where provenance or paging matters. */
export async function apiGetWithMeta<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<{ data: T; meta: Record<string, unknown> }> {
  const response = await api.get<ApiEnvelope<T>>(url, config);
  return { data: unwrap(response.data), meta: response.data.meta ?? {} };
}

function unwrap<T>(envelope: ApiEnvelope<T>): T {
  if (envelope && typeof envelope === "object" && "data" in envelope) {
    return envelope.data as T;
  }
  return envelope as unknown as T;
}

/** Same as apiPost but keeps `meta` - used where the result carries a side note. */
export async function apiPostWithMeta<T>(
  url: string,
  body?: unknown,
  config?: AxiosRequestConfig,
): Promise<{ data: T; meta: Record<string, unknown> }> {
  const response = await api.post<ApiEnvelope<T>>(url, body ?? {}, config);
  return { data: unwrap(response.data), meta: response.data.meta ?? {} };
}

/**
 * A `multipart/form-data` POST - file uploads.
 *
 * This instance sets a default `Content-Type: application/json` header, and
 * axios does *not* replace an explicitly-set header just because the body is
 * `FormData` - it silently sends the multipart bytes labelled as JSON, which
 * the backend then fails to parse. Overriding it to `undefined` here is what
 * makes axios compute the real header (with the multipart boundary) itself.
 */
/**
 * Fetch a file through the authenticated client and save it.
 *
 * Deliberately not an `<a href>`: that resolves against the frontend origin
 * rather than the API, and cannot carry the bearer token, so it lands on a 404
 * or 401 HTML page which the browser then saves as the "downloaded file".
 *
 * Returns the filename actually saved, taken from Content-Disposition when the
 * server supplies one.
 */
export async function apiDownload(
  url: string,
  fallbackName: string,
  config?: AxiosRequestConfig,
): Promise<string> {
  const response = await api.get<Blob>(url, { ...config, responseType: "blob" });

  const disposition = String(response.headers?.["content-disposition"] ?? "");
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;

  const href = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(href), 10_000);

  return filename;
}

export async function apiUpload<T>(url: string, form: FormData): Promise<T> {
  const response = await api.post<ApiEnvelope<T>>(url, form, {
    headers: { "Content-Type": undefined },
  });
  return unwrap(response.data);
}
