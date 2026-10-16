import { useMemo, useState } from "react";

import type { Route } from "../api/types";
import { clockWithDay, milesPrecise } from "../lib/format";
import { RISK_COLORS, RISK_TEXT, riskLabel } from "../lib/risk";

interface Props {
  route: Route;
}

/**
 * Every checkpoint, with the forecast that scored it.
 *
 * A 1,000-mile trip at 10-mile spacing is 101 rows, which is a lot of DOM
 * for something a user mostly scans for the red ones — so the default
 * view is the checkpoints that are not Low, with the full list one click
 * away. That keeps the common case small without hiding anything.
 */
export function CheckpointTable({ route }: Props) {
  const [showAll, setShowAll] = useState(false);

  const { rows, hiddenCount } = useMemo(() => {
    const notable = route.checkpoints.filter((cp) => (cp.risk?.level ?? 0) !== 1);
    const visible = showAll || notable.length === 0 ? route.checkpoints : notable;
    return { rows: visible, hiddenCount: route.checkpoints.length - visible.length };
  }, [route, showAll]);

  return (
    <section className="checkpoints">
      <header className="checkpoints__head">
        <h3>
          Checkpoints <span className="muted">({route.checkpoints.length})</span>
        </h3>
        {hiddenCount > 0 && (
          <button type="button" className="button button--link" onClick={() => setShowAll(true)}>
            Show {hiddenCount} low-risk
          </button>
        )}
        {showAll && (
          <button type="button" className="button button--link" onClick={() => setShowAll(false)}>
            Show only notable
          </button>
        )}
      </header>

      {rows.length === 0 ? (
        <p className="muted">No checkpoints were scored on this route.</p>
      ) : (
        <div className="checkpoints__scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Mile</th>
                <th scope="col">ETA</th>
                <th scope="col">Risk</th>
                <th scope="col">Wind</th>
                <th scope="col">Rain</th>
                <th scope="col">Snow</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((cp) => {
                const level = cp.risk?.level ?? 0;
                return (
                  <tr key={cp.index}>
                    <td>{milesPrecise(cp.distance_miles)}</td>
                    <td>{clockWithDay(cp.eta)}</td>
                    <td>
                      <span
                        className="pill"
                        style={{ background: RISK_COLORS[level], color: RISK_TEXT[level] }}
                        title={cp.risk?.load_rule ?? `Driven by ${cp.risk?.driver ?? "no data"}`}
                      >
                        {riskLabel(level)}
                        {cp.risk?.load_rule ? " ·load" : ""}
                      </span>
                    </td>
                    <td>{cp.weather ? `${cp.weather.wind_mph.toFixed(0)}` : "—"}</td>
                    <td>{cp.weather ? cp.weather.rain_in_hr.toFixed(2) : "—"}</td>
                    <td>{cp.weather ? cp.weather.snow_in_hr.toFixed(2) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="checkpoints__units muted">
        Wind in mph, rain and snow in inches per hour, at each checkpoint's own arrival time.
      </p>
    </section>
  );
}
