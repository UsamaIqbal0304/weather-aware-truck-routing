/** Display helpers. Every number the user sees is formatted here. */

const MILES = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const MILES_1DP = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const POUNDS = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function miles(value: number): string {
  return `${MILES.format(value)} mi`;
}

export function milesPrecise(value: number): string {
  return `${MILES_1DP.format(value)} mi`;
}

export function pounds(value: number): string {
  return `${POUNDS.format(value)} lb`;
}

/** 17.83 -> "17h 50m". Drivers think in hours and minutes, not decimals. */
export function duration(hours: number): string {
  const total = Math.round(hours * 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

/**
 * Times are rendered in the browser's zone, with the zone named.
 *
 * A trip that crosses three time zones has no single correct local clock,
 * so picking the viewer's and labelling it is the only honest option — an
 * unlabelled time would be read as the checkpoint's own local time.
 */
const TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

const CLOCK_WITH_DAY = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

const FULL = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

export function clock(iso: string | null): string {
  return iso ? CLOCK.format(new Date(iso)) : "—";
}

export function clockWithDay(iso: string | null): string {
  return iso ? CLOCK_WITH_DAY.format(new Date(iso)) : "—";
}

export function fullTime(iso: string | null): string {
  return iso ? FULL.format(new Date(iso)) : "—";
}

export function timeZoneName(): string {
  return TIME_ZONE;
}

/** The value a <input type="datetime-local"> expects, in local time. */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** A datetime-local value is zoneless; read it as local and send UTC. */
export function fromLocalInputValue(value: string): string {
  return new Date(value).toISOString();
}
