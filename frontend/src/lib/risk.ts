import type { RiskLevel } from "../api/types";

/**
 * One colour scale for the whole app: map lines, checkpoint dots, heatmap,
 * summary bars and table rows all read from here, so a Severe checkpoint is
 * the same colour everywhere it appears.
 *
 * The ramp runs green -> amber -> orange -> red -> near-black rather than a
 * single hue, because the five bands are ordered categories a driver has to
 * tell apart at a glance on a moving map. It is also distinguishable with
 * deuteranopia: lightness falls monotonically across the ramp, so the bands
 * separate by brightness even when the hues do not.
 */
export const RISK_COLORS: Record<RiskLevel, string> = {
  0: "#9aa4b2", // no forecast at this hour
  1: "#2e9e5b",
  2: "#e0a300",
  3: "#ef6c1a",
  4: "#d12d2d",
  5: "#6b1020",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  0: "No data",
  1: "Low",
  2: "Moderate",
  3: "High",
  4: "Severe",
  5: "No Travel",
};

/** Dark text on the two light bands, white on the rest. */
export const RISK_TEXT: Record<RiskLevel, string> = {
  0: "#10151c",
  1: "#ffffff",
  2: "#241a00",
  3: "#ffffff",
  4: "#ffffff",
  5: "#ffffff",
};

export function riskColor(level: number | null | undefined): string {
  return RISK_COLORS[(level ?? 0) as RiskLevel] ?? RISK_COLORS[0];
}

export function riskLabel(level: number | null | undefined): string {
  return RISK_LABELS[(level ?? 0) as RiskLevel] ?? "No data";
}

/** The ordered bands, for legends and summary bars. */
export const RISK_BANDS: RiskLevel[] = [1, 2, 3, 4, 5];

/**
 * The brief's thresholds, restated for the UI so the legend can show the
 * driver what a band means without a round trip. Kept as display strings
 * only — nothing here classifies anything; the server owns that.
 */
export const THRESHOLD_TABLE = [
  { condition: "Wind", unit: "mph", bands: ["< 25", "25 – 34", "35 – 44", "45 – 54", "≥ 55"] },
  {
    condition: "Rain",
    unit: "in/hr",
    bands: ["< 0.10", "0.10 – 0.25", "0.25 – 0.50", "0.50 – 1.00", "> 1.00"],
  },
  {
    condition: "Snow",
    unit: "in/hr",
    bands: ["< 0.5", "0.5 – 1.0", "1.0 – 2.0", "2.0 – 3.0", "> 3.0"],
  },
] as const;

export const LOAD_RULES = [
  "≥ 55 mph — No Travel for any load",
  "45 – 54 mph with more than 30,000 lb — No Travel",
  "35 – 44 mph with more than 40,000 lb — Severe",
] as const;
