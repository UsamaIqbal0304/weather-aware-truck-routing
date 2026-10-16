import { useId, useState } from "react";

import type { PlanRequest } from "../api/types";
import { PRESETS, type Endpoint } from "../lib/presets";
import { fromLocalInputValue, pounds, toLocalInputValue } from "../lib/format";

interface Props {
  busy: boolean;
  errorField?: string;
  onSubmit: (request: PlanRequest) => void;
}

const SPACINGS = [10, 25, 50] as const;

/** Tomorrow at 06:00 local — a plausible dispatch time, and comfortably
 * inside the forecast horizon whenever the page is opened. */
function defaultDeparture(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(6, 0, 0, 0);
  return toLocalInputValue(date);
}

/** A free-text endpoint, or a preset that already carries its coordinate. */
type EndpointState = { text: string; fixed: Endpoint | null };

function toField(state: EndpointState): PlanRequest["origin"] {
  return state.fixed && state.fixed.name === state.text
    ? { name: state.fixed.name, lon: state.fixed.lon, lat: state.fixed.lat }
    : state.text;
}

export function PlanForm({ busy, errorField, onSubmit }: Props) {
  const ids = {
    origin: useId(),
    destination: useId(),
    departure: useId(),
    load: useId(),
  };

  const [origin, setOrigin] = useState<EndpointState>({
    text: PRESETS[0].origin.name,
    fixed: PRESETS[0].origin,
  });
  const [destination, setDestination] = useState<EndpointState>({
    text: PRESETS[0].destination.name,
    fixed: PRESETS[0].destination,
  });
  const [departure, setDeparture] = useState(defaultDeparture);
  const [loadLb, setLoadLb] = useState(42000);
  const [spacing, setSpacing] = useState<(typeof SPACINGS)[number]>(25);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    onSubmit({
      origin: toField(origin),
      destination: toField(destination),
      departure: fromLocalInputValue(departure),
      load_lb: loadLb,
      spacing_miles: spacing,
    });
  };

  const invalid = (field: string) => (errorField === field ? "field field--invalid" : "field");

  return (
    <form className="form" onSubmit={submit}>
      <div className="form__presets" role="group" aria-label="Example corridors">
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            className="chip"
            title={preset.note}
            onClick={() => {
              setOrigin({ text: preset.origin.name, fixed: preset.origin });
              setDestination({ text: preset.destination.name, fixed: preset.destination });
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className={invalid("origin")}>
        <label htmlFor={ids.origin}>Origin</label>
        <input
          id={ids.origin}
          value={origin.text}
          placeholder="City, state — or 41.88,-87.63"
          autoComplete="off"
          onChange={(e) => setOrigin({ text: e.target.value, fixed: origin.fixed })}
          required
        />
      </div>

      <div className={invalid("destination")}>
        <label htmlFor={ids.destination}>Destination</label>
        <input
          id={ids.destination}
          value={destination.text}
          placeholder="City, state — or 39.74,-104.99"
          autoComplete="off"
          onChange={(e) => setDestination({ text: e.target.value, fixed: destination.fixed })}
          required
        />
      </div>

      <div className={invalid("departure")}>
        <label htmlFor={ids.departure}>Departure</label>
        <input
          id={ids.departure}
          type="datetime-local"
          value={departure}
          onChange={(e) => setDeparture(e.target.value)}
          required
        />
      </div>

      <div className={invalid("load_lb")}>
        <label htmlFor={ids.load}>
          Load weight <span className="field__value">{pounds(loadLb)}</span>
        </label>
        <input
          id={ids.load}
          type="range"
          min={0}
          max={80000}
          step={1000}
          value={loadLb}
          onChange={(e) => setLoadLb(Number(e.target.value))}
        />
        {/* The two numbers below are where the brief's load rules switch on,
            so they are marked rather than left for the driver to find. */}
        <div className="field__ticks">
          <span>0</span>
          <span className="tick tick--30">30k</span>
          <span className="tick tick--40">40k</span>
          <span>80k</span>
        </div>
      </div>

      <fieldset className={invalid("spacing_miles")}>
        <legend>Sample weather every</legend>
        <div className="segmented">
          {SPACINGS.map((value) => (
            <button
              key={value}
              type="button"
              className={value === spacing ? "segmented__item is-active" : "segmented__item"}
              aria-pressed={value === spacing}
              onClick={() => setSpacing(value)}
            >
              {value} mi
            </button>
          ))}
        </div>
      </fieldset>

      <button className="button button--primary" type="submit" disabled={busy}>
        {busy ? "Planning…" : "Plan routes"}
      </button>
    </form>
  );
}
