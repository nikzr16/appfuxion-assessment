/**
 * Display formatting. Money and quantities arrive as decimal strings and are formatted as
 * strings: they never pass through `Number`, so no float error can creep in (PRD D9).
 */

export const EMPTY = "—";
const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

const minorUnitCache = new Map<string, number>();

/** Digits after the decimal point for a currency (MYR 2, JPY 0, KWD 3); 2 when unknown. */
export function minorUnits(currency: string | null): number {
  if (!currency) return 2;
  const cached = minorUnitCache.get(currency);
  if (cached !== undefined) return cached;
  let digits = 2;
  try {
    digits =
      new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions()
        .maximumFractionDigits ?? 2;
  } catch {
    // Not a currency Intl knows: keep the default.
  }
  minorUnitCache.set(currency, digits);
  return digits;
}

function groupThousands(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Groups the integer part and pads the fraction to `minFraction` digits. A longer fraction
 * is kept as printed (never rounded). Strings that are not plain decimals come back as-is.
 */
export function formatDecimal(value: string, minFraction = 0): string {
  const match = DECIMAL.exec(value.trim());
  if (!match) return value;
  const [, sign = "", integer = "0", fraction = ""] = match;
  const padded = fraction.padEnd(minFraction, "0");
  return `${sign}${groupThousands(integer)}${padded ? `.${padded}` : ""}`;
}

/** `1234.5` + `MYR` → `1,234.50` (no currency code). */
export function formatAmount(value: string | null, currency: string | null): string {
  if (value === null || value === "") return EMPTY;
  return formatDecimal(value, minorUnits(currency));
}

/** `1234.5` + `MYR` → `MYR 1,234.50`; without a currency only the number. */
export function formatMoney(value: string | null, currency: string | null): string {
  const amount = formatAmount(value, currency);
  if (amount === EMPTY || !currency) return amount;
  return `${currency} ${amount}`;
}

/** Quantities: grouping only, decimals exactly as printed. */
export function formatQuantity(value: string | null): string {
  if (value === null || value === "") return EMPTY;
  return formatDecimal(value);
}

/** ISO `2025-03-04` → `04-03-2025` by string split (no Date, so no time-zone shift). */
export function formatDate(value: string | null): string {
  if (!value) return EMPTY;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}-${match[2]}-${match[1]}` : value;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO timestamp → `DD-MM-YYYY HH:mm` in the browser's local time. */
export function formatTimestamp(value: string | null): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const day = `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()}`;
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** `3 minutes ago`, `yesterday`, `just now`. */
export function formatRelative(value: string, now: number = Date.now()): string {
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return "";
  const seconds = Math.round((time - now) / 1000);
  if (Math.abs(seconds) < 45) return "just now";
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return rtf.format(Math.round(seconds / 60), "minute");
}

/** File sizes: `512 B`, `842 KB`, `2.4 MB`. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Step durations: `850 ms`, `3.2 s`, `1 min 5 s`. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`;
}

const KIND_BY_TYPE: Record<string, string> = {
  "application/pdf": "PDF",
  "image/jpeg": "JPG",
  "image/png": "PNG",
};

/** Short file kind for a content type: `PDF`, `JPG`, `PNG`. */
export function fileKind(contentType: string): string {
  return KIND_BY_TYPE[contentType] ?? (contentType.split("/")[1] ?? contentType).toUpperCase();
}

/** Token counts: `842`, `9,120`, `12.3k`, `1.2M`. */
export function formatTokens(tokens: number): string {
  if (tokens < 10_000) return groupThousands(String(Math.round(tokens)));
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${(tokens / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

const MICROS = /^(\d+)(?:\.(\d{1,6}))?\d*$/;

/** A USD decimal string → whole micro-dollars (exact; never through floating point). */
export function costMicros(value: string): number {
  const match = MICROS.exec(value.trim());
  if (!match) return 0;
  const [, whole = "0", fraction = ""] = match;
  return Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
}

/** Micro-dollars → a 6-place USD decimal string. */
export function microsToCost(micros: number): string {
  const whole = Math.floor(micros / 1_000_000);
  return `${whole}.${String(micros % 1_000_000).padStart(6, "0")}`;
}

/**
 * Estimated USD cost: `$0.0012` below a cent, `$0.042` below a dollar, `$1.24` above;
 * `<$0.0001` for a tiny non-zero cost; `—` when unknown (an unpriced model).
 */
export function formatCost(value: string | null): string {
  if (value === null) return EMPTY;
  const micros = costMicros(value);
  if (micros === 0) return "$0.00";
  if (micros < 100) return "<$0.0001";
  const dollars = micros / 1_000_000;
  const digits = micros < 10_000 ? 4 : micros < 1_000_000 ? 3 : 2;
  return `$${dollars.toFixed(digits)}`;
}

/** A 0–1 ratio as a percentage: `80%`, `99.5%`; `—` when unknown. */
export function formatPercent(ratio: number | null): string {
  if (ratio === null) return EMPTY;
  const percent = Math.round(ratio * 1000) / 10;
  return `${Number.isInteger(percent) ? percent.toFixed(0) : percent.toFixed(1)}%`;
}
