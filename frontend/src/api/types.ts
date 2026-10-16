/**
 * The shape of /api/plan, mirroring backend/trucking/api/serializers.py.
 *
 * Hand-written rather than generated: there is one endpoint and the
 * contract is small enough that a generator would be more moving parts
 * than it saves. Every coordinate is [lon, lat] — GeoJSON order, the
 * same order MapLibre wants, so nothing in this app ever flips a pair.
 */

/** 1 Low, 2 Moderate, 3 High, 4 Severe, 5 No Travel. 0 means no forecast. */
export type RiskLevel = 0 | 1 | 2 | 3 | 4 | 5;

export type Coord = [number, number];

export interface Place {
  query: string;
  name: string;
  lon: number;
  lat: number;
}

export interface WeatherSample {
  valid_time: string;
  wind_mph: number;
  wind_gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  temperature_f: number | null;
}

export interface RiskAssessment {
  level: RiskLevel;
  label: string;
  wind_level: RiskLevel;
  rain_level: RiskLevel;
  snow_level: RiskLevel;
  /** Which condition produced the level: "wind" | "rain" | "snow" | "clear". */
  driver: string;
  /** Set when a load rule raised the level beyond the plain wind band. */
  load_rule: string | null;
}

export interface Checkpoint {
  index: number;
  lon: number;
  lat: number;
  distance_miles: number;
  covered_miles: number;
  elapsed_hours: number;
  eta: string | null;
  weather: WeatherSample | null;
  risk: RiskAssessment | null;
}

export interface RouteSummary {
  distance_miles: number;
  duration_hours: number;
  severe_miles: number;
  high_miles: number;
  moderate_miles: number;
  low_miles: number;
  no_travel_miles: number;
  average_risk: number;
  max_risk: RiskLevel;
  max_risk_label: string;
  assessed_miles: number;
  unassessed_miles: number;
}

export interface Route {
  id: string;
  name: string;
  source: string;
  rank: number;
  recommended: boolean;
  blocked: boolean;
  distance_miles: number;
  duration_hours: number;
  arrival: string | null;
  geometry: Coord[];
  summary: RouteSummary | null;
  checkpoints: Checkpoint[];
}

/**
 * Hour-major frames: levels[hour][point]. The slider changes the hour and
 * redraws every corridor point, so one frame is one contiguous array.
 */
export interface HeatmapFrames {
  points: Coord[];
  levels: RiskLevel[][];
  wind_mph: number[][];
  rain_in_hr: number[][];
  snow_in_hr: number[][];
}

export interface PlanResponse {
  request: {
    origin: Place;
    destination: Place;
    departure: string;
    load_lb: number;
    spacing_miles: number;
  };
  recommendation: {
    route_id: string | null;
    reason: string | null;
    warning: string | null;
  };
  routes: Route[];
  heatmap: {
    hour_offsets: number[];
    by_route: Record<string, HeatmapFrames>;
  };
  notes: string[];
  meta: {
    weather_cells: number;
    elapsed_ms: number;
    checkpoints: number;
    attribution: Record<string, string>;
  };
}

export interface ApiErrorBody {
  error: { code: string; message: string; field?: string; service?: string };
}

export interface PlanRequest {
  origin: string | { name: string; lon: number; lat: number };
  destination: string | { name: string; lon: number; lat: number };
  departure: string;
  load_lb: number;
  spacing_miles: 10 | 25 | 50;
}
