"use client";

import { X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Model } from "@/engine/model";
import { READY_POWER, normalizeTag, type Player } from "@/lib/player";

import { Sheet, cn } from "./ui";

const KEY = "mira.player-tag";

const readTag = () => {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
};
const writeTag = (tag: string | null) => {
  try {
    if (tag) localStorage.setItem(KEY, tag);
    else localStorage.removeItem(KEY);
  } catch {
    // Private mode or blocked storage: the tag just isn't remembered.
  }
};

async function fetchPlayer(tag: string): Promise<Player> {
  const res = await fetch(`/api/player/${tag}`);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.error ?? "Couldn’t look that tag up.");
  return body as Player;
}

/**
 * The connected player: a tag remembered in this browser, looked up through /api/player. There's no
 * account behind it; Brawl Stars has no login, so a tag is just "whose brawlers to draft with".
 */
export function usePlayer() {
  const [player, setPlayer] = useState<Player | null>(null);
  const [loading, setLoading] = useState(false);

  // Reconnect the remembered tag once on load. A failure (renamed, network) just leaves you disconnected.
  useEffect(() => {
    const tag = readTag();
    if (!tag) return;
    let live = true;
    fetchPlayer(tag)
      .then((p) => live && setPlayer(p))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  /** Look up a typed tag; resolves to an error message, or null on success. */
  const connect = useCallback(async (raw: string): Promise<string | null> => {
    const tag = normalizeTag(raw);
    if (!tag) return "That isn’t a valid player tag. It’s the code under your name on your profile.";
    setLoading(true);
    try {
      const p = await fetchPlayer(tag);
      setPlayer(p);
      writeTag(p.tag);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : "Couldn’t look that tag up.";
    } finally {
      setLoading(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    setPlayer(null);
    writeTag(null);
  }, []);

  return { player, loading, connect, disconnect };
}

/** Model indices of the brawlers this player has at power 11, or null when nobody is connected. */
export function useReady(model: Model, player: Player | null): ReadonlySet<number> | null {
  return useMemo(() => {
    if (!player) return null;
    const ready = new Set(player.brawlers.filter((b) => b.power >= READY_POWER).map((b) => b.id));
    const out = new Set<number>();
    model.ids.forEach((id, b) => ready.has(id) && out.add(b));
    return out;
  }, [model, player]);
}

/** Corner pill: "Connect your tag" or the connected player's name. Opens the connect sheet. */
export function PlayerButton({ player, onOpen, dark }: { player: Player | null; onOpen: () => void; dark?: boolean }) {
  return (
    <button
      onClick={onOpen}
      className={cn(
        "pressable flex h-10 shrink-0 items-center gap-2 rounded-full px-4 text-sm font-semibold",
        dark ? "bg-white/[0.08] hover:bg-white/[0.14]" : "bg-subtle text-foreground/80 hover:text-foreground",
      )}
    >
      {player ? (
        <>
          <span className="max-w-[10rem] truncate">{player.name}</span>
          <span className="tabular font-medium text-muted">{player.trophies.toLocaleString()}</span>
        </>
      ) : (
        "Connect your tag"
      )}
    </button>
  );
}

/** The connect / disconnect sheet. */
export function PlayerSheet({
  open,
  onClose,
  player,
  ready,
  loading,
  connect,
  disconnect,
}: {
  open: boolean;
  onClose: () => void;
  player: Player | null;
  ready: ReadonlySet<number> | null;
  loading: boolean;
  connect: (raw: string) => Promise<string | null>;
  disconnect: () => void;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const err = await connect(value);
    if (err) setError(err);
    else {
      setValue("");
      onClose();
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title={player ? "Your account" : "Connect your tag"} initialFocus={player ? undefined : input}>
      {player ? (
        <div className="space-y-5 pb-2">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0">
              <span className="block truncate text-xl font-bold">{player.name}</span>
              <span className="tabular text-sm text-muted">#{player.tag}</span>
            </span>
            <span className="tabular shrink-0 text-sm text-muted">{player.trophies.toLocaleString()} trophies</span>
          </div>
          <p className="text-[15px] leading-relaxed text-muted">
            <strong className="tabular text-foreground">{ready?.size ?? 0}</strong> of your {player.brawlers.length} brawlers are at power 11.
            Drafts can stick to those.
          </p>
          <button onClick={disconnect} className="pressable h-11 rounded-full bg-subtle px-5 text-sm font-semibold text-muted hover:text-foreground">
            Disconnect
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3 pb-2">
          <p className="text-[15px] leading-relaxed text-muted">
            Your tag is under your name on your in-game profile. Mira reads which brawlers you have at power 11 and can draft with those.
          </p>
          <div className="flex gap-2">
            <label className="flex h-12 min-w-0 flex-1 items-center gap-1 rounded-full bg-subtle px-5 ring-foreground focus-within:ring-2">
              <span className="text-muted" aria-hidden>
                #
              </span>
              <input
                ref={input}
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  setError(null);
                }}
                placeholder="your tag"
                aria-label="Player tag"
                aria-invalid={!!error}
                aria-describedby={error ? "tag-error" : undefined}
                autoComplete="off"
                autoCapitalize="characters"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="go"
                className="tabular h-full min-w-0 flex-1 bg-transparent text-base uppercase outline-none placeholder:text-faint placeholder:normal-case focus-visible:outline-none"
              />
            </label>
            <button
              type="submit"
              disabled={loading || !value.trim()}
              className="pressable h-12 shrink-0 rounded-full bg-foreground px-5 text-sm font-bold text-background disabled:opacity-40"
            >
              {loading ? "Looking up…" : "Connect"}
            </button>
          </div>
          {error && (
            <p id="tag-error" role="alert" className="flex items-start gap-1.5 px-1 text-sm text-them">
              <X size={16} strokeWidth={2} absoluteStrokeWidth className="mt-0.5 shrink-0" />
              {error}
            </p>
          )}
        </form>
      )}
    </Sheet>
  );
}
