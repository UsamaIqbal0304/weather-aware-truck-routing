import { useCallback, useRef, useState } from "react";

import { ApiError, fetchPlan } from "../api/client";
import type { PlanRequest, PlanResponse } from "../api/types";

type Status = "idle" | "loading" | "ready" | "error";

/**
 * Owns the one network call this app makes.
 *
 * An in-flight request is aborted when a new one starts. A plan takes a
 * few seconds against three free APIs, and without this a user who
 * changes the load weight and re-submits can watch the older, slower
 * response land on top of the newer one.
 */
export function usePlan() {
  const [status, setStatus] = useState<Status>("idle");
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const inFlight = useRef<AbortController | null>(null);
  const lastRequest = useRef<PlanRequest | null>(null);

  const run = useCallback(async (request: PlanRequest) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    lastRequest.current = request;

    setStatus("loading");
    setError(null);
    try {
      const response = await fetchPlan(request, controller.signal);
      if (controller.signal.aborted) return;
      setPlan(response);
      setStatus("ready");
    } catch (caught) {
      if ((caught as Error)?.name === "AbortError") return;
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, { code: "unknown", message: String(caught) }),
      );
      setStatus("error");
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
    }
  }, []);

  const retry = useCallback(() => {
    if (lastRequest.current) void run(lastRequest.current);
  }, [run]);

  return { status, plan, error, run, retry };
}
