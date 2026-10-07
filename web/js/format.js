// Formatting helpers for numbers, durations and times.

// Floor to an integer and group thousands with commas (keep minus sign).
export function fmtNum(n) {
  const value = Math.floor(Number(n) || 0);
  const sign = value < 0 ? '-' : '';
  return sign + Math.abs(value).toLocaleString('en-US');
}

// Whole seconds (rounded up) as 'H:MM:SS'.
export function fmtDuration(seconds) {
  let total = Math.ceil(Number(seconds) || 0);
  if (total < 0) total = 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// Local date-time string for an ISO timestamp, or '' for falsy input.
export function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('th-TH');
}

// Number with at most one decimal and grouped thousands (for hourly rates such as 19.6).
export function fmtRate(n) {
  const value = Math.round((Number(n) || 0) * 10) / 10;
  return value.toLocaleString('en-US', { maximumFractionDigits: 1 });
}
