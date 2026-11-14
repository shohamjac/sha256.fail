const whole = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

/** 27088 -> "27,088". A fractional mean keeps one decimal: 27088.5 -> "27,088.5". */
export function count(value: number): string {
  return Number.isInteger(value) ? whole.format(value) : oneDecimal.format(value);
}

/** 22510128 -> "22.5M"; 950 -> "950"; 12900 -> "12.9K". */
export function compact(value: number): string {
  const units: [number, string][] = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
  for (const [size, suffix] of units) {
    if (Math.abs(value) >= size) {
      const scaled = value / size;
      return `${scaled >= 100 ? Math.round(scaled) : Number(scaled.toFixed(1))}${suffix}`;
    }
  }
  return whole.format(value);
}

/** "2026-11-14T10:07:12+00:00" -> "14 Nov 2026" (UTC). */
export function date(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return parsed.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}
