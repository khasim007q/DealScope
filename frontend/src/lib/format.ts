const nf = new Intl.NumberFormat("en-US");

export function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "n/a";
  return nf.format(Math.round(n));
}

export function formatCredits(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "n/a";
  const rounded = Math.round(n * 10) / 10;
  return nf.format(rounded);
}

/** Signed percentage with one decimal, e.g. +12.3% / -4.0%. Input is already a percent value. */
export function formatSignedPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "n/a";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(1)}%`;
}

export function formatPct(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "n/a";
  return `${n.toFixed(digits)}%`;
}

/** Ratio in 0..1 formatted as percent. */
export function formatRate(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "n/a";
  return `${Math.round(n * 100)}%`;
}

export function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return iso ? iso : "n/a";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return iso ? iso : "n/a";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return "";
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  const d = parseDate(iso);
  if (!d) return "n/a";
  const diff = Math.round((now - d.getTime()) / 1000);
  if (diff < 0) return "just now";
  if (diff < 45) return "just now";
  if (diff < 90) return "a minute ago";
  const mins = Math.round(diff / 60);
  if (mins < 60) return `${mins} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return days === 1 ? "yesterday" : `${days} days ago`;
  return formatDate(iso);
}

/** Milliseconds as "850 ms", "1.5 s" or "2 min 5 s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "n/a";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1).replace(/\.?0+$/, "")} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

export function plural(n: number, one: string, many?: string): string {
  return n === 1 ? one : (many ?? `${one}s`);
}

/** Encode each path segment after the leading "evidence/" for the evidence endpoint. */
export function evidenceUrl(repoPath: string): string {
  const rel = repoPath.replace(/^\/+/, "").replace(/^evidence\//, "");
  return "/api/evidence/" + rel.split("/").map(encodeURIComponent).join("/");
}

/** Normalize a user-entered domain: strip protocol, www, paths, whitespace, lowercase. */
export function normalizeDomain(raw: string): string {
  let s = raw.trim().toLowerCase();
  s = s.replace(/^[a-z]+:\/\//, "");
  s = s.replace(/^www\./, "");
  s = s.split(/[/?#]/)[0] ?? "";
  return s.replace(/[,;]+$/, "");
}

const DOMAIN_RE = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/;

export function isValidDomain(d: string): boolean {
  return DOMAIN_RE.test(d);
}

export function splitDomains(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map(normalizeDomain)
    .filter((d) => d.length > 0);
}
