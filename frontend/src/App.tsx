import { useCallback, useEffect, useMemo, useState } from "react";

import type { PlanRequest } from "./api/types";
import { CheckpointTable } from "./components/CheckpointTable";
import { Legend } from "./components/Legend";
import { MapView } from "./components/MapView";
import { PlanForm } from "./components/PlanForm";
import { RecommendationBanner } from "./components/RecommendationBanner";
import { RouteList } from "./components/RouteList";
import { TimeSlider } from "./components/TimeSlider";
import { usePlan } from "./hooks/usePlan";
import { timeZoneName } from "./lib/format";

export default function App() {
  const { status, plan, error, run, retry } = usePlan();
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [showHeatmap, setShowHeatmap] = useState(true);

  // A new plan selects the recommended route and rewinds the slider, so
  // the first thing on screen is the answer at the departure hour.
  useEffect(() => {
    if (!plan) return;
    setSelectedRouteId(plan.recommendation.route_id ?? plan.routes[0]?.id ?? null);
    setHour(0);
    setPlaying(false);
  }, [plan]);

  const selectedRoute = useMemo(
    () => plan?.routes.find((route) => route.id === selectedRouteId) ?? null,
    [plan, selectedRouteId],
  );

  const maxHour = plan ? plan.heatmap.hour_offsets.length - 1 : 48;

  const submit = useCallback((request: PlanRequest) => void run(request), [run]);

  return (
    <div className="layout">
      <aside className="panel">
        <header className="panel__head">
          <h1>Weather-Aware Truck Routing</h1>
          <p className="panel__sub">
            Three candidate routes, scored on the forecast at the hour the truck actually
            reaches each checkpoint. Times shown in {timeZoneName()}.
          </p>
        </header>

        <PlanForm busy={status === "loading"} errorField={error?.field} onSubmit={submit} />

        {status === "error" && error && (
          <div className="banner banner--error" role="alert">
            <p className="banner__title">Could not plan this trip</p>
            <p className="banner__reason">{error.message}</p>
            {error.retryable && (
              <button type="button" className="button button--link" onClick={retry}>
                Try again
              </button>
            )}
          </div>
        )}

        {status === "loading" && (
          <div className="banner banner--busy" role="status">
            <p className="banner__title">Planning…</p>
            <p className="banner__reason">
              Generating routes, then sampling the forecast at every checkpoint's arrival time.
            </p>
          </div>
        )}

        {plan && status !== "loading" && (
          <>
            <RecommendationBanner plan={plan} onShow={setSelectedRouteId} />
            <RouteList
              routes={plan.routes}
              selectedRouteId={selectedRouteId}
              onSelect={setSelectedRouteId}
            />
            <Legend />
            {selectedRoute && <CheckpointTable route={selectedRoute} />}
            <footer className="panel__foot">
              <p>
                {plan.meta.checkpoints} checkpoints · {plan.meta.weather_cells} forecast cells ·
                planned in {(plan.meta.elapsed_ms / 1000).toFixed(1)}s
              </p>
              <p className="muted">
                Routing {plan.meta.attribution.routing}. Weather {plan.meta.attribution.weather}.
              </p>
            </footer>
          </>
        )}

        {status === "idle" && (
          <div className="banner">
            <p className="banner__title">Pick a corridor and plan</p>
            <p className="banner__reason">
              Everything is computed live from public routing and forecast services, so the risk
              you see is tomorrow's real weather, not a fixture.
            </p>
          </div>
        )}
      </aside>

      <main className={plan ? "stage stage--planned" : "stage"}>
        <MapView
          plan={plan}
          selectedRouteId={selectedRouteId}
          hour={hour}
          showHeatmap={showHeatmap}
          onSelectRoute={setSelectedRouteId}
        />
        {plan && (
          <TimeSlider
            departure={plan.request.departure}
            hour={hour}
            maxHour={maxHour}
            playing={playing}
            showHeatmap={showHeatmap}
            onHourChange={setHour}
            onTogglePlay={() => setPlaying((value) => !value)}
            onToggleHeatmap={setShowHeatmap}
          />
        )}
      </main>
    </div>
  );
}
