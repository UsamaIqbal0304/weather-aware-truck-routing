import { useEffect, useRef } from "react";

import { fullTime } from "../lib/format";

interface Props {
  departure: string;
  hour: number;
  maxHour: number;
  playing: boolean;
  showHeatmap: boolean;
  onHourChange: (hour: number) => void;
  onTogglePlay: () => void;
  onToggleHeatmap: (visible: boolean) => void;
}

/** Milliseconds per animation step. ~7 fps reads as weather moving rather
 * than flickering, and leaves the map plenty of budget between frames. */
const STEP_MS = 140;

/**
 * The 0-48 hour forecast slider.
 *
 * Playback is driven by setTimeout rather than requestAnimationFrame on
 * purpose: this is a fixed-rate animation through discrete hourly frames,
 * not a continuous one, and rAF would fire ~8 times per frame only to
 * discard seven of them. It also keeps playing at the same rate on a
 * 120 Hz display.
 */
export function TimeSlider({
  departure,
  hour,
  maxHour,
  playing,
  showHeatmap,
  onHourChange,
  onTogglePlay,
  onToggleHeatmap,
}: Props) {
  const tick = useRef(onHourChange);
  tick.current = onHourChange;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      tick.current((hour + 1) % (maxHour + 1));
    }, STEP_MS);
    return () => window.clearInterval(timer);
  }, [playing, hour, maxHour]);

  const when = new Date(new Date(departure).getTime() + hour * 3600_000).toISOString();

  return (
    <div className="slider">
      <div className="slider__row">
        <button
          type="button"
          className="button button--icon"
          onClick={onTogglePlay}
          aria-label={playing ? "Pause forecast playback" : "Play forecast playback"}
        >
          {playing ? "❚❚" : "▶"}
        </button>

        <input
          className="slider__input"
          type="range"
          min={0}
          max={maxHour}
          step={1}
          value={hour}
          aria-label="Forecast hour after departure"
          aria-valuetext={`${hour} hours after departure, ${fullTime(when)}`}
          onChange={(event) => onHourChange(Number(event.target.value))}
        />

        <div className="slider__readout">
          <strong>+{hour} h</strong>
          <span>{fullTime(when)}</span>
        </div>
      </div>

      <div className="slider__row slider__row--meta">
        <label className="switch">
          <input
            type="checkbox"
            checked={showHeatmap}
            onChange={(event) => onToggleHeatmap(event.target.checked)}
          />
          <span>Corridor heatmap</span>
        </label>
        <span className="slider__hint">
          Forecast along the selected route's corridor, {maxHour} hours from departure.
          Checkpoint colours stay fixed at each truck's own arrival time.
        </span>
      </div>
    </div>
  );
}
