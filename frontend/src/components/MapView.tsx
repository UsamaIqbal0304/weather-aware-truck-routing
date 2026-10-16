import maplibregl, { type Map as MapLibreMap, type MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Checkpoint, HeatmapFrames, PlanResponse, Route } from "../api/types";
import { boundsOf, checkpointFeatures, riskSegments } from "../lib/geo";
import { clock, milesPrecise } from "../lib/format";
import { RISK_COLORS, riskLabel } from "../lib/risk";

/**
 * The map. One MapLibre instance for the life of the page; everything
 * after that is a source update.
 *
 * The performance rule this file follows is: never rebuild what did not
 * change. Dragging the forecast slider must touch only the heatmap
 * source, because that is a per-frame operation, while selecting a route
 * rebuilds the route and checkpoint sources, which happens on a click.
 * Each lives in its own effect with its own dependency list for exactly
 * that reason.
 */

/**
 * A keyless basemap. OpenFreeMap serves OpenStreetMap vector tiles with no
 * API key and no sign-up, which is what lets this repo be cloned and run
 * without a secret; CARTO's and Stadia's equivalents now watermark every
 * tile unless a key is attached. "Positron" is the pale variant — the route
 * lines are the content here, and a grey backdrop is the one that does not
 * compete with five risk colours drawn on top of it.
 */
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/**
 * The basemap style carries its own OpenStreetMap and OpenFreeMap credits,
 * so this adds only the two services that produced the overlay.
 */
const ATTRIBUTION =
  'Routing <a href="https://project-osrm.org/">OSRM</a> · ' +
  'Weather <a href="https://open-meteo.com/">Open-Meteo</a>';

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

/** Risk ordinal -> paint colour, as a MapLibre match expression. */
const LEVEL_COLOR: maplibregl.DataDrivenPropertyValueSpecification<string> = [
  "match",
  ["get", "level"],
  1,
  RISK_COLORS[1],
  2,
  RISK_COLORS[2],
  3,
  RISK_COLORS[3],
  4,
  RISK_COLORS[4],
  5,
  RISK_COLORS[5],
  RISK_COLORS[0],
];

interface Props {
  plan: PlanResponse | null;
  selectedRouteId: string | null;
  hour: number;
  showHeatmap: boolean;
  onSelectRoute: (routeId: string) => void;
}

function heatmapCollection(frames: HeatmapFrames, hour: number): GeoJSON.FeatureCollection {
  const levels = frames.levels[hour] ?? [];
  return {
    type: "FeatureCollection",
    features: frames.points.map((point, i) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: point },
      properties: {
        level: levels[i] ?? 0,
        // The heatmap layer wants a 0-1 weight. Low keeps a small floor so
        // the corridor is always visible as a calm green band — a layer that
        // renders nothing on a quiet day is indistinguishable from a broken
        // one — and the remaining range is spread across the four bands
        // above it, which is where the eye needs the contrast.
        weight: (levels[i] ?? 0) <= 0 ? 0 : 0.14 + (((levels[i] ?? 0) - 1) / 4) * 0.86,
        wind: frames.wind_mph[hour]?.[i] ?? 0,
        rain: frames.rain_in_hr[hour]?.[i] ?? 0,
        snow: frames.snow_in_hr[hour]?.[i] ?? 0,
      },
    })),
  };
}

function popupHtml(route: Route, cp: Checkpoint): string {
  const w = cp.weather;
  const level = cp.risk?.level ?? 0;
  const rows: Array<[string, string]> = [
    ["Mile", milesPrecise(cp.distance_miles)],
    ["ETA", clock(cp.eta)],
    ["Wind", w ? `${w.wind_mph.toFixed(0)} mph (gust ${w.wind_gust_mph.toFixed(0)})` : "—"],
    ["Rain", w ? `${w.rain_in_hr.toFixed(2)} in/hr` : "—"],
    ["Snow", w ? `${w.snow_in_hr.toFixed(2)} in/hr` : "—"],
    ["Temp", w?.temperature_f != null ? `${w.temperature_f.toFixed(0)} °F` : "—"],
  ];
  const escape = (text: string) =>
    text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  return `
    <div class="popup">
      <div class="popup__head" style="background:${RISK_COLORS[level as 0]}">
        ${escape(route.name)} · ${escape(riskLabel(level))}
      </div>
      <dl class="popup__body">
        ${rows.map(([k, v]) => `<dt>${k}</dt><dd>${escape(v)}</dd>`).join("")}
      </dl>
      ${cp.risk?.load_rule ? `<p class="popup__rule">${escape(cp.risk.load_rule)}</p>` : ""}
    </div>`;
}

/**
 * MapLibre needs WebGL, and a few machines do not have it — remote desktops,
 * locked-down corporate builds, a browser with hardware acceleration off.
 * Constructing the map would throw there, and an uncaught throw in render
 * takes the whole page down, so the map is the one piece allowed to fail on
 * its own: the panel keeps working and the map area explains itself.
 */
function webglAvailable(): boolean {
  try {
    const probe = document.createElement("canvas");
    return Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
  } catch {
    return false;
  }
}

export function MapView({ plan, selectedRouteId, hour, showHeatmap, onSelectRoute }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const ready = useRef(false);
  const popup = useRef<maplibregl.Popup | null>(null);
  // Read inside map event handlers, which are registered once and would
  // otherwise close over the first render's props.
  const latest = useRef({ plan, selectedRouteId, onSelectRoute });
  latest.current = { plan, selectedRouteId, onSelectRoute };
  const [failed, setFailed] = useState(false);

  // --- create the map once -------------------------------------------------
  useEffect(() => {
    if (map.current || !container.current) return;
    if (!webglAvailable()) {
      setFailed(true);
      return;
    }

    let instance: MapLibreMap;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: BASEMAP_STYLE,
        center: [-98.5, 39.5],
        zoom: 3.4,
        attributionControl: { compact: true, customAttribution: ATTRIBUTION },
        // The checkpoint and heatmap layers are the content; a tilted or
        // rotated view only makes them harder to compare.
        pitchWithRotate: false,
        dragRotate: false,
        touchZoomRotate: false,
        // Redrawing the heatmap on every slider step is cheap on the GPU but
        // not free on the CPU if the map is also re-rendering antialiased
        // tiles at high DPR on a laptop.
        fadeDuration: 0,
      });
      instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      instance.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");
      map.current = instance;
    } catch (error) {
      // A WebGL context can still fail to initialise after the probe above
      // passes — a lost context, a blocklisted driver. Same outcome.
      console.error("Map could not be initialised", error);
      setFailed(true);
      return;
    }

    instance.on("load", () => {
      instance.addSource("heat", { type: "geojson", data: EMPTY });
      instance.addSource("others", { type: "geojson", data: EMPTY });
      instance.addSource("selected", { type: "geojson", data: EMPTY });
      instance.addSource("checkpoints", { type: "geojson", data: EMPTY });

      instance.addLayer({
        id: "heat",
        type: "heatmap",
        source: "heat",
        layout: { visibility: "none" },
        paint: {
          "heatmap-weight": ["get", "weight"],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 3, 1.1, 10, 2.4],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 3, 26, 7, 70, 11, 150],
          "heatmap-opacity": 0.75,
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0,
            "rgba(0,0,0,0)",
            0.2,
            "rgba(46,158,91,0.45)",
            0.4,
            "rgba(224,163,0,0.6)",
            0.6,
            "rgba(239,108,26,0.72)",
            0.8,
            "rgba(209,45,45,0.82)",
            1,
            "rgba(107,16,32,0.9)",
          ],
        },
      });

      // Unselected candidates: thin, grey, still clickable.
      instance.addLayer({
        id: "others-casing",
        type: "line",
        source: "others",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.8 },
      });
      instance.addLayer({
        id: "others-line",
        type: "line",
        source: "others",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#64748b",
          "line-width": 3,
          "line-dasharray": [2, 1.4],
          "line-opacity": 0.95,
        },
      });

      // Selected candidate: wide, and coloured segment by segment with the
      // risk at the checkpoints bounding each segment.
      instance.addLayer({
        id: "selected-casing",
        type: "line",
        source: "selected",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#0f172a", "line-width": 9, "line-opacity": 0.35 },
      });
      instance.addLayer({
        id: "selected-line",
        type: "line",
        source: "selected",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": LEVEL_COLOR, "line-width": 5 },
      });

      instance.addLayer({
        id: "checkpoints",
        type: "circle",
        source: "checkpoints",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 3.4, 7, 6, 12, 9],
          "circle-color": LEVEL_COLOR,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.4,
        },
      });

      ready.current = true;
      instance.fire("spotter:ready");
    });

    const onCheckpointClick = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      const current = latest.current;
      if (!feature || !current.plan) return;
      const route = current.plan.routes.find((r) => r.id === current.selectedRouteId);
      const cp = route?.checkpoints[Number(feature.properties?.index)];
      if (!route || !cp) return;
      popup.current?.remove();
      popup.current = new maplibregl.Popup({ closeButton: true, maxWidth: "260px" })
        .setLngLat([cp.lon, cp.lat])
        .setHTML(popupHtml(route, cp))
        .addTo(instance);
    };

    const onRouteClick = (event: MapLayerMouseEvent) => {
      const routeId = event.features?.[0]?.properties?.routeId;
      if (typeof routeId === "string") latest.current.onSelectRoute(routeId);
    };

    instance.on("click", "checkpoints", onCheckpointClick);
    instance.on("click", "others-line", onRouteClick);
    for (const layer of ["checkpoints", "others-line"]) {
      instance.on("mouseenter", layer, () => {
        instance.getCanvas().style.cursor = "pointer";
      });
      instance.on("mouseleave", layer, () => {
        instance.getCanvas().style.cursor = "";
      });
    }

    return () => {
      instance.remove();
      map.current = null;
      ready.current = false;
    };
  }, []);

  // --- routes and checkpoints: change when the plan or selection does ------
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    const draw = () => {
      // An open popup belongs to the route it was opened on, so it is stale
      // the moment the selection or the plan changes.
      popup.current?.remove();
      const others = instance.getSource("others") as maplibregl.GeoJSONSource | undefined;
      const selected = instance.getSource("selected") as maplibregl.GeoJSONSource | undefined;
      const points = instance.getSource("checkpoints") as maplibregl.GeoJSONSource | undefined;
      if (!others || !selected || !points) return;

      if (!plan) {
        others.setData(EMPTY);
        selected.setData(EMPTY);
        points.setData(EMPTY);
        return;
      }

      const current = plan.routes.find((r) => r.id === selectedRouteId) ?? plan.routes[0];

      others.setData({
        type: "FeatureCollection",
        features: plan.routes
          .filter((r) => r.id !== current?.id)
          .map((r) => ({
            type: "Feature" as const,
            geometry: { type: "LineString" as const, coordinates: r.geometry },
            properties: { routeId: r.id, name: r.name },
          })),
      });

      selected.setData({
        type: "FeatureCollection",
        features: current ? riskSegments(current) : [],
      });
      points.setData({
        type: "FeatureCollection",
        features: current ? checkpointFeatures(current) : [],
      });
    };

    if (ready.current) draw();
    else instance.once("spotter:ready", draw);
  }, [plan, selectedRouteId]);

  // --- fit the view, but only when the trip itself changes -----------------
  // Keyed on the endpoints rather than the plan object, so re-planning the
  // same trip with a heavier load does not yank the camera back.
  const tripKey = plan
    ? `${plan.request.origin.lon},${plan.request.origin.lat}->` +
      `${plan.request.destination.lon},${plan.request.destination.lat}`
    : null;

  useEffect(() => {
    const instance = map.current;
    if (!instance || !plan) return;
    const bounds = boundsOf(plan.routes.flatMap((r) => r.geometry));
    if (!bounds) return;
    const fit = () =>
      instance.fitBounds(bounds, { padding: { top: 60, bottom: 90, left: 60, right: 60 }, duration: 700 });
    if (ready.current) fit();
    else instance.once("spotter:ready", fit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tripKey]);

  // --- heatmap: the only thing the slider touches --------------------------
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    const draw = () => {
      const source = instance.getSource("heat") as maplibregl.GeoJSONSource | undefined;
      if (!source) return;
      const frames = plan && selectedRouteId ? plan.heatmap.by_route[selectedRouteId] : null;
      source.setData(frames ? heatmapCollection(frames, hour) : EMPTY);
      if (instance.getLayer("heat")) {
        instance.setLayoutProperty("heat", "visibility", showHeatmap && frames ? "visible" : "none");
      }
    };

    if (ready.current) draw();
    else instance.once("spotter:ready", draw);
  }, [plan, selectedRouteId, hour, showHeatmap]);

  if (failed) {
    return (
      <div className="map map--failed" role="status">
        <div className="map__fallback">
          <p className="map__fallback-title">The map needs WebGL</p>
          <p>
            This browser could not open a WebGL context, so the map cannot draw. Every number
            behind it — the ranking, the per-checkpoint risk and the forecast that produced it —
            is still in the panel on the left.
          </p>
        </div>
      </div>
    );
  }

  return <div className="map" ref={container} role="application" aria-label="Route map" />;
}
