import { useState, type ReactNode } from "react";
import type { RunMode, Tone } from "../api/types";

export function Icon({ name, size = 18 }: { name: "info" | "warn" | "check" | "x" | "download" | "copy" | "external" | "play"; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
  };
  switch (name) {
    case "info":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v6M12 7.5v.01" />
        </svg>
      );
    case "warn":
      return (
        <svg {...common}>
          <path d="M12 3l10 18H2L12 3z" />
          <path d="M12 10v5M12 18v.01" />
        </svg>
      );
    case "check":
      return (
        <svg {...common}>
          <path d="M4 12l5 5L20 6" />
        </svg>
      );
    case "x":
      return (
        <svg {...common}>
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      );
    case "download":
      return (
        <svg {...common}>
          <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
        </svg>
      );
    case "copy":
      return (
        <svg {...common}>
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V6a2 2 0 012-2h9" />
        </svg>
      );
    case "external":
      return (
        <svg {...common}>
          <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" />
        </svg>
      );
    case "play":
      return (
        <svg {...common}>
          <path d="M7 4l13 8-13 8V4z" />
        </svg>
      );
  }
}

export function StatusPill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`pill tone-${tone}`}>{children}</span>;
}

export function ModeBadge({ mode, large = false }: { mode: RunMode; large?: boolean }) {
  if (mode === "synthetic") {
    return (
      <span className={`badge mode-synthetic${large ? " banner-demo" : ""}`}>Synthetic demo data</span>
    );
  }
  return <span className="badge mode-live">Live data</span>;
}

export function Banner({ tone, title, children, className = "" }: { tone: Tone; title?: string; children?: ReactNode; className?: string }) {
  return (
    <div className={`banner tone-${tone} ${className}`} role={tone === "bad" ? "alert" : "note"}>
      <Icon name={tone === "bad" || tone === "caution" ? "warn" : "info"} />
      <div>
        {title ? <strong>{title}</strong> : null}
        {children ? <p>{children}</p> : null}
      </div>
    </div>
  );
}

export function Loading({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <div>{label}</div>
    </div>
  );
}

export function ErrorBox({ title = "Something went wrong", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <strong>{title}</strong>
      <span>{message}</span>
      {onRetry ? (
        <div style={{ marginTop: 8 }}>
          <button type="button" className="btn small" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function EmptyBox({ children }: { children: ReactNode }) {
  return <div className="empty-box">{children}</div>;
}

export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary>{summary}</summary>
      <div className="disc-body">{children}</div>
    </details>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("done");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 1800);
  };
  return (
    <button type="button" className="btn small" onClick={onClick} aria-label={`${label} ${text}`}>
      <Icon name={state === "done" ? "check" : "copy"} size={14} />
      <span aria-live="polite">{state === "done" ? "Copied" : state === "failed" ? "Copy failed" : label}</span>
    </button>
  );
}

export function Meter({
  name,
  valueText,
  percent,
  tone,
  sub,
}: {
  name: string;
  valueText: string;
  percent: number | null;
  tone: Tone;
  sub?: string;
}) {
  const pct = percent === null ? 0 : Math.max(0, Math.min(100, percent));
  return (
    <div className={`tone-${tone}`}>
      <div className="meter-head">
        <span className="meter-name">{name}</span>
        <span className="meter-val">{valueText}</span>
      </div>
      <div
        className="meter-track"
        role="meter"
        aria-label={name}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent === null ? undefined : Math.round(pct)}
        aria-valuetext={valueText}
      >
        <div className="meter-fill" style={{ width: `${pct}%` }} />
      </div>
      {sub ? <div className="meter-sub">{sub}</div> : null}
    </div>
  );
}

export function SectionHead({ id, title, subtitle }: { id?: string; title: string; subtitle?: string }) {
  return (
    <div className="section-head">
      <h2 id={id}>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
  );
}
