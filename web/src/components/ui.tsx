"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { displayName, hue, initials } from "@/lib/names";

export function cn(...xs: (string | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

/** Brawler token: colored initials (no game art yet). */
export function Avatar({ id, name, size = 28 }: { id: number; name: string; size?: number }) {
  const h = hue(id);
  return (
    <span
      aria-hidden
      className="avatar inline-grid shrink-0 place-items-center rounded-full font-semibold tabular"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.38), ["--h" as string]: h }}
    >
      {initials(name)}
    </span>
  );
}

export function BrawlerChip({ id, name, size = "md" }: { id: number; name: string; size?: "sm" | "md" }) {
  return (
    <span className={cn("inline-flex min-w-0 items-center", size === "sm" ? "gap-1.5" : "gap-2")}>
      <Avatar id={id} name={name} size={size === "sm" ? 20 : 28} />
      <span className={cn("truncate font-medium", size === "sm" ? "text-[13px]" : "text-[15px]")}>{displayName(name)}</span>
    </span>
  );
}

export function Badge({ tone, children, title }: { tone: "warn" | "accent" | "muted"; children: ReactNode; title?: string }) {
  const tones = {
    warn: "bg-warn-soft text-warn",
    accent: "bg-accent-soft text-accent",
    muted: "bg-surface-2 text-muted",
  };
  return (
    <span title={title} className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold", tones[tone])}>
      {children}
    </span>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  // Outer radius 12 = inner 8 + padding 4 (concentric).
  return (
    <div role="radiogroup" aria-label={label} className="grid grid-flow-col auto-cols-fr gap-1 rounded-[12px] bg-surface-2 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "pressable min-h-10 rounded-[8px] px-3 text-[14px] font-medium",
            o.value === value ? "surface bg-raised text-text" : "text-muted",
          )}
        >
          {o.label}
        </button>
      ))}
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
      <div
        className="sheet-backdrop absolute inset-0 bg-black/40"
        style={{ opacity: open ? 1 : 0 }}
        onClick={onClose}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        data-open={open}
        className={cn(
          "sheet absolute inset-x-0 bottom-0 mx-auto flex max-h-[85dvh] w-full max-w-[560px] flex-col",
          "rounded-t-[20px] bg-surface outline-none",
        )}
        style={{ opacity: open ? 1 : 0, boxShadow: "var(--shadow-sheet)" }}
      >
        <div className="flex items-center justify-between px-4 pt-3 pb-2">
          <h2 className="text-[17px] font-semibold">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="pressable -me-2 grid size-10 place-items-center rounded-full text-muted"
          >
            <X size={18} strokeWidth={2} absoluteStrokeWidth />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {children}
        </div>
      </div>
    </div>
  );
}
