// Pure helpers. Times: a UTC instant is shifted by the volcano's offset and read in UTC, so the browser's own time
// zone never enters. Numbers: as the English bulletins print them (vigil.agent.render).

const pad = (n) => String(n).padStart(2, "0");
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

function shifted(when, offsetHours) {
  if (!/(Z|[+-]\d\d:\d\d)$/.test(when)) throw new Error(`not a time with its zone: ${when}`);
  return new Date(Date.parse(when) + offsetHours * 3_600_000);
}

export function localTime(when, offsetHours, seconds = false) {
  const d = shifted(when, offsetHours);
  const hm = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  return seconds ? `${hm}:${pad(d.getUTCSeconds())}` : hm;
}

export function localDate(when, offsetHours) {
  const d = shifted(when, offsetHours);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

// A time as the page shows it beside the clock: the local time, with the local date in front when the day is not
// the clock's own (live data can be days old, and two bare times would read in the wrong order).
export function stamp(when, clock, offsetHours, seconds = false) {
  const time = localTime(when, offsetHours, seconds);
  const date = localDate(when, offsetHours);
  return date === localDate(clock, offsetHours) ? time : `${date} ${time}`;
}

export function zone(offsetHours) {
  if (offsetHours === 0) return "UTC";
  return `UTC${offsetHours < 0 ? "−" : "+"}${Math.abs(offsetHours)}`;
}

export function number(value, decimals = 0) {
  return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function plusMinus(value, sigma, unit) {
  if (unit === "deg") return `${number(value, 1)}° ± ${number(sigma, 1)}°`;
  if (unit === "m2") return `${number(value / 1e6, 1)} ± ${number(sigma / 1e6, 1)} km²`;
  return `${number(value)} ± ${number(sigma)} m`;
}

export const FOOT = 0.3048;
export const feet = (metres) => Math.round(metres / FOOT);

export function age(when, clock) {
  const minutes = (Date.parse(clock) - Date.parse(when)) / 60_000;
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.floor(minutes)} min ago`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return `${Math.floor(minutes / 1440)} d ago`;
}

export function ticks(start, end, stepMinutes) {
  const out = [], last = Date.parse(end), step = stepMinutes * 60_000;
  for (let t = Date.parse(start) + step; t < last; t += step) out.push(iso(t));
  return [...out, iso(last)];
}

const R = 6_371_008.8, rad = (d) => (d * Math.PI) / 180, deg = (r) => (r * 180) / Math.PI;

export function destination(lat, lon, bearingDeg, metres) {
  const d = metres / R, b = rad(bearingDeg), p1 = rad(lat), l1 = rad(lon);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [deg(p2), deg(l2)];
}

export function bearing(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

// "KPcam (wide view, plume height)" -> "KPcam"
export const shortName = (name) => name.split(" (")[0];
