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
