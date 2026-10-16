import type { ApiErrorBody, PlanRequest, PlanResponse } from "./types";

/**
 * A plan request that failed in a way worth showing the user verbatim.
 *
 * ``field`` is set when the backend could name the input at fault, which
 * is what lets the form highlight it rather than printing a banner the
 * user has to map back onto a control themselves.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly field?: string;
  readonly status: number;
  /** True when retrying unchanged could plausibly work: a 502 from a
   * free upstream, or a network drop. A 400 is not retryable. */
  readonly retryable: boolean;

  constructor(status: number, body: Partial<ApiErrorBody["error"]>) {
    super(body.message ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code ?? "unknown";
    this.field = body.field;
    this.retryable = status >= 500 || status === 0;
  }
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if ((cause as Error)?.name === "AbortError") throw cause;
    throw new ApiError(0, {
      code: "network",
      message: "Could not reach the planning service. Check your connection.",
    });
  }

  if (!response.ok) {
    let parsed: Partial<ApiErrorBody["error"]> = {};
    try {
      parsed = ((await response.json()) as ApiErrorBody).error ?? {};
    } catch {
      // A non-JSON error body means something in front of the app failed
      // (a proxy, a cold-start timeout). The status is all we have.
    }
    throw new ApiError(response.status, parsed);
  }

  return (await response.json()) as T;
}

export function fetchPlan(request: PlanRequest, signal?: AbortSignal): Promise<PlanResponse> {
  return post<PlanResponse>("/api/plan", request, signal);
}
