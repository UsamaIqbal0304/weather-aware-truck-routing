/**
 * Long US freight corridors, with coordinates.
 *
 * Two reasons these carry a coordinate rather than just a name. It makes
 * the demo one click instead of two text fields, and it lets the request
 * skip the geocoder entirely — one fewer call against Nominatim's free
 * server, which is both faster and politer.
 */
export interface Endpoint {
  name: string;
  lon: number;
  lat: number;
}

export interface Preset {
  label: string;
  note: string;
  origin: Endpoint;
  destination: Endpoint;
}

export const PRESETS: Preset[] = [
  {
    label: "Chicago → Denver",
    note: "I-80 across the plains — the classic crosswind corridor",
    origin: { name: "Chicago, IL", lon: -87.6298, lat: 41.8781 },
    destination: { name: "Denver, CO", lon: -104.9903, lat: 39.7392 },
  },
  {
    label: "Seattle → Salt Lake City",
    note: "Mountain passes; the route most likely to show snow bands",
    origin: { name: "Seattle, WA", lon: -122.3321, lat: 47.6062 },
    destination: { name: "Salt Lake City, UT", lon: -111.891, lat: 40.7608 },
  },
  {
    label: "Dallas → Atlanta",
    note: "Gulf moisture — the route most likely to show rain bands",
    origin: { name: "Dallas, TX", lon: -96.797, lat: 32.7767 },
    destination: { name: "Atlanta, GA", lon: -84.388, lat: 33.749 },
  },
  {
    label: "Los Angeles → Phoenix",
    note: "A short desert run, useful for the 10-mile sampling interval",
    origin: { name: "Los Angeles, CA", lon: -118.2437, lat: 34.0522 },
    destination: { name: "Phoenix, AZ", lon: -112.074, lat: 33.4484 },
  },
];
