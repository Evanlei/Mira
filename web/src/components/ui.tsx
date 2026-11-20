"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { modeInfo, portrait } from "@/lib/art";
import { hue, initials } from "@/lib/names";

export function cn(...xs: (string | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

/** Brawler portrait (game art), or colored initials if we don't have the art. */
export function Portrait({
  id,
  name,
  size,
  className,
  style,
}: {
  id: number;
  name: string;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const src = portrait(id);
  const box = size ? { width: size, height: size } : undefined;
  if (!src)
    return (
      <span
        aria-hidden
        className={cn("avatar inline-grid shrink-0 place-items-center font-semibold", className)}
        style={{ ...box, fontSize: size ? Math.round(size * 0.36) : undefined, ["--h" as string]: hue(id), ...style }}
      >
        {initials(name)}
      </span>
    );
  return (
    // eslint-disable-next-line @next/next/no-img-element -- small static PNGs; no optimizer needed
    <img
      src={src}
      alt=""
      width={size ?? 170}
      height={size ?? 170}
      loading="lazy"
      decoding="async"
      draggable={false}
      className={cn("art shrink-0 bg-subtle object-cover", className)}
      style={{ ...box, ...style }}
    />
  );
}

/** Small overlapping portraits, like the inline icon clusters on jmo's portfolio. */
export function Cluster({ model, picks, size = 24 }: { model: { ids: number[]; names: string[] }; picks: number[]; size?: number }) {
  return (
    <span className="inline-flex shrink-0 align-middle">
      {picks.map((b, i) => (
        <Portrait
          key={b}
          id={model.ids[b]}
          name={model.names[b]}
          size={size}
          className={cn("rounded-full ring-2 ring-background", i > 0 && "-ms-2")}
        />
      ))}
    </span>
  );
}

export function ModeIcon({ mode, size = 16 }: { mode: string; size?: number }) {
  const m = modeInfo(mode);
  if (!m.icon) return <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: m.color }} />;
  // eslint-disable-next-line @next/next/no-img-element -- transparent icon art
  return <img src={m.icon} alt="" width={size} height={size} className="inline-block shrink-0 object-contain align-middle" style={{ width: size, height: size }} />;
}

export function Chip({ children, title, tone = "default" }: { children: ReactNode; title?: string; tone?: "default" | "warn" }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] leading-none",
        tone === "warn" ? "border-warn/30 text-warn" : "border-border text-muted",
      )}
    >
      {children}
    </span>
  );
}

/** "A / B" tabs with a hairline underline under the active one (jmo's ViewToggle). */
export function SlashTabs<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled,
  hint,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
  disabled?: boolean;
  hint?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} aria-disabled={disabled} className="flex items-center gap-2">
      {options.map((o, i) => (
        <span key={o.value} className="flex items-center gap-2">
          {i > 0 && <span className="text-sm text-faint/60">/</span>}
          <button
            role="radio"
            aria-checked={o.value === value}
            onClick={() => onChange(o.value)}
            disabled={disabled && o.value !== value}
            className={cn(
              "relative min-h-9 pb-1 text-sm transition-colors duration-150 disabled:opacity-40",
              o.value === value ? "text-foreground" : "text-muted/70 enabled:hover:text-muted",
            )}
          >
            {o.label}
            {o.value === value && <span className="absolute inset-x-0 bottom-1.5 h-px bg-foreground/40" />}
          </button>
        </span>
      ))}
      {hint && <span className="ms-auto text-xs text-faint">{hint}</span>}
    </div>
  );
}

/** Bottom sheet. Stays mounted so open/close are transitions that can reverse mid-flight. */
export function Sheet({
  open,
  onClose,
  title,
  children,
  initialFocus,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  initialFocus?: React.RefObject<HTMLElement | null>;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => (initialFocus?.current ?? panel.current)?.focus(), 50);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose, initialFocus]);

  return (
    <div className={cn("fixed inset-0 z-50", !open && "pointer-events-none")} inert={!open}>
      <div className="sheet-backdrop absolute inset-0 bg-black/30 dark:bg-black/60" style={{ opacity: open ? 1 : 0 }} onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        data-open={open}
        className="sheet absolute inset-x-0 bottom-0 mx-auto flex max-h-[88dvh] w-full max-w-2xl flex-col rounded-t-[22px] border border-transparent bg-background outline-none"
        style={{ opacity: open ? 1 : 0, boxShadow: "var(--shadow-border), 0 -12px 40px oklch(0 0 0 / 0.12)" }}
      >
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="pressable -me-2 grid size-10 place-items-center rounded-full text-muted hover:text-foreground">
            <X size={18} strokeWidth={1.5} absoluteStrokeWidth />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-[max(20px,env(safe-area-inset-bottom))]">{children}</div>
      </div>
    </div>
  );
}
