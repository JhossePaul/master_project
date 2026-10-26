const LOCALE = "es-MX";
const ZONE = "America/Mexico_City";

const NO_VALUE = "—";

function isNum(x: number | null | undefined): x is number {
  return x !== null && x !== undefined && Number.isFinite(x);
}

function fixed(x: number, digits: number): string {
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(x);
}

export function formatInt(x: number | null | undefined): string {
  return isNum(x)
    ? new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 }).format(x)
    : NO_VALUE;
}

/** Recibe una fracción: 0.123 -> "12.3 %". */
export function formatPct(x: number | null | undefined, digits = 1): string {
  return isNum(x) ? `${fixed(x * 100, digits)} %` : NO_VALUE;
}

/** "12.3 % [11.0, 13.6]"; sin intervalo, solo la estimación. */
export function formatCi(
  est: number | null | undefined,
  lo: number | null | undefined,
  hi: number | null | undefined,
): string {
  if (!isNum(est)) return NO_VALUE;
  if (!isNum(lo) || !isNum(hi)) return formatPct(est);
  return `${formatPct(est)} [${fixed(lo * 100, 1)}, ${fixed(hi * 100, 1)}]`;
}

/** Diferencia en estrellas con signo: "+0.21 ★". */
export function formatStars(x: number | null | undefined): string {
  if (!isNum(x)) return NO_VALUE;
  const sign = x > 0 ? "+" : x < 0 ? "−" : "";
  return `${sign}${fixed(Math.abs(x), 2)} ★`;
}

export function formatKappa(x: number | null | undefined): string {
  return isNum(x) ? fixed(x, 3) : NO_VALUE;
}

function toDate(value: Date | string | null | undefined): Date | null {
  if (value === null || value === undefined) return null;
  // "2026-10-25" es un día calendario: se lee en UTC para no correrlo.
  const date =
    typeof value === "string" && value.length === 10
      ? new Date(`${value}T00:00:00Z`)
      : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function clean(text: string): string {
  return text.replace(/\./g, "").replace(/\s+/g, " ").trim();
}

export function formatDate(value: Date | string | null | undefined): string {
  const date = toDate(value);
  if (!date) return NO_VALUE;
  const tz = typeof value === "string" && value.length === 10 ? "UTC" : ZONE;
  return clean(
    new Intl.DateTimeFormat(LOCALE, {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: tz,
    }).format(date),
  ).replace(/ de /g, " ");
}

/** "oct 2026"; acepta "2026-10" o una fecha. */
export function formatMonth(value: Date | string | null | undefined): string {
  const date = toDate(
    typeof value === "string" && value.length === 7 ? `${value}-01` : value,
  );
  if (!date) return NO_VALUE;
  return clean(
    new Intl.DateTimeFormat(LOCALE, {
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    }).format(date),
  ).replace(/ de /g, " ");
}

/** "25 oct 2026, 09:30 CDMX". */
export function formatDateTime(
  value: Date | string | null | undefined,
): string {
  const date = toDate(value);
  if (!date) return NO_VALUE;
  const time = new Intl.DateTimeFormat(LOCALE, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: ZONE,
  }).format(date);
  const day = clean(
    new Intl.DateTimeFormat(LOCALE, {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: ZONE,
    }).format(date),
  ).replace(/ de /g, " ");
  return `${day}, ${time} CDMX`;
}

export function formatBytes(x: number | null | undefined): string {
  if (!isNum(x)) return NO_VALUE;
  if (x < 1024) return `${formatInt(x)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = x / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${fixed(value, 1)} ${units[i]}`;
}

/** "[−0.45, −0.30]" para el intervalo de una diferencia en estrellas. */
export function formatStarsInterval(
  lo: number | null | undefined,
  hi: number | null | undefined,
): string {
  if (!isNum(lo) || !isNum(hi)) return "";
  const signed = (x: number) => `${x < 0 ? "−" : ""}${fixed(Math.abs(x), 2)}`;
  return `[${signed(lo)}, ${signed(hi)}]`;
}

/** "[11.0, 13.6]" para el intervalo de una proporción. */
export function formatPctInterval(
  lo: number | null | undefined,
  hi: number | null | undefined,
): string {
  if (!isNum(lo) || !isNum(hi)) return "";
  return `[${fixed(lo * 100, 1)}, ${fixed(hi * 100, 1)}]`;
}
