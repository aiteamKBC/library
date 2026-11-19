const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const AWARE_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$/i;

function parseCalendarDate(value: string): Date | null {
  if (!DATE_ONLY.test(value) || Number(value.slice(0, 4)) < 1) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value ? date : null;
}

// Never append Z to an API timestamp or reinterpret an unlabelled wall time.
// The offset already identifies the instant; Intl performs the only conversion.
function parseTimestamp(value: string): Date | null {
  if (!AWARE_TIMESTAMP.test(value) || !parseCalendarDate(value.slice(0, 10))) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function getDeviceTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

// DateFields are calendar values; absolute DateTimes use the viewer's device.
export function libraryCalendarDate(value: string | Date = new Date(), timeZone = getDeviceTimeZone()): string {
  if (typeof value === "string" && DATE_ONLY.test(value)) return parseCalendarDate(value) ? value : "";
  const date = value instanceof Date ? value : parseTimestamp(value);
  if (!date || Number.isNaN(date.getTime()) || !timeZone) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(date);
    const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
    return `${part("year")}-${part("month")}-${part("day")}`;
  } catch {
    return "";
  }
}

export function formatLibraryDate(
  value?: string | null,
  options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" },
  fallback = "-",
): string {
  if (!value) return fallback;
  const dateOnly = DATE_ONLY.test(value);
  const date = dateOnly ? parseCalendarDate(value) : parseTimestamp(value);
  if (!date) return fallback;
  const timeZone = dateOnly ? "UTC" : options.timeZone ?? getDeviceTimeZone();
  if (!timeZone) return fallback;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      ...options, timeZone,
    }).format(date);
  } catch {
    return fallback;
  }
}

export function formatLibraryTimestamp(value?: string | null, fallback = "-"): string {
  // A DateField must not acquire an invented midnight when passed to this helper.
  if (value && DATE_ONLY.test(value)) return formatLibraryDate(value, undefined, fallback);
  return formatLibraryDate(value, {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short",
  }, fallback);
}

export function libraryCalendarDayTimestamp(value?: string | null): number | null {
  if (!value) return null;
  const day = libraryCalendarDate(value);
  if (!day) return null;
  return Date.parse(`${day}T00:00:00Z`);
}
