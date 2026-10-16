import type { Checkpoint, Coord, Route } from "../api/types";

/** Great-circle distance in miles. Mirrors the server's constant. */
const EARTH_RADIUS_MILES = 3958.7613;

export function haversineMiles(a: Coord, b: Coord): number {
  const toRad = Math.PI / 180;
  const p1 = a[1] * toRad;
  const p2 = b[1] * toRad;
  const dp = p2 - p1;
  const dl = (b[0] - a[0]) * toRad;
  const h =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_MILES * Math.asin(Math.sqrt(h));
}

export type Bounds = [[number, number], [number, number]];

export function boundsOf(coords: Coord[]): Bounds | null {
  if (coords.length === 0) return null;
  let west = coords[0][0];
  let east = coords[0][0];
  let south = coords[0][1];
  let north = coords[0][1];
  for (const [lon, lat] of coords) {
    if (lon < west) west = lon;
    if (lon > east) east = lon;
    if (lat < south) south = lat;
    if (lat > north) north = lat;
  }
  return [
    [west, south],
    [east, north],
  ];
}

/**
 * Cut a route's polyline at its checkpoints, so each piece can be drawn in
 * the colour of the risk at that checkpoint.
 *
 * The geometry sent to the browser is decimated, so a checkpoint's
 * ``distance_miles`` (measured on the full-resolution line) does not index
 * into it directly. Walking the decimated line and accumulating real
 * distance, then scaling checkpoint distances by the ratio of the two
 * lengths, keeps the cut points within a vertex of where they belong —
 * well under the width of the stroke that will be drawn over them.
 */
export function riskSegments(route: Route): GeoJSON.Feature<GeoJSON.LineString>[] {
  const line = route.geometry;
  const checkpoints = route.checkpoints;
  if (line.length < 2 || checkpoints.length === 0) return [];

  const cumulative: number[] = [0];
  for (let i = 1; i < line.length; i += 1) {
    cumulative.push(cumulative[i - 1] + haversineMiles(line[i - 1], line[i]));
  }
  const drawnLength = cumulative[cumulative.length - 1];
  const reportedLength = route.distance_miles || drawnLength;
  const scale = drawnLength > 0 ? drawnLength / reportedLength : 1;

  const features: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  let vertex = 0;

  for (let i = 0; i < checkpoints.length - 1; i += 1) {
    const from = checkpoints[i];
    const to = checkpoints[i + 1];
    const endAt = to.distance_miles * scale;

    const coordinates: Coord[] = [[from.lon, from.lat]];
    while (vertex < line.length && cumulative[vertex] < endAt) {
      coordinates.push(line[vertex]);
      vertex += 1;
    }
    coordinates.push([to.lon, to.lat]);

    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates },
      properties: {
        // The span between two checkpoints is drawn at the worse of the
        // two, so a Severe checkpoint is never approached down a line
        // coloured calm.
        level: Math.max(from.risk?.level ?? 0, to.risk?.level ?? 0),
        from: from.index,
      },
    });
  }

  return features;
}

export function checkpointFeatures(route: Route): GeoJSON.Feature<GeoJSON.Point>[] {
  return route.checkpoints.map((cp: Checkpoint) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [cp.lon, cp.lat] },
    properties: {
      index: cp.index,
      level: cp.risk?.level ?? 0,
      routeId: route.id,
    },
  }));
}
