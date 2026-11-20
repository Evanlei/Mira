import type { NextRequest } from "next/server";

import { normalizeTag, type Player } from "@/lib/player";

// Brawl Stars API keys only work from whitelisted IPs, and Vercel's change, so production goes through
// RoyaleAPI's fixed-IP proxy (whitelist 45.79.218.79 on the key). Locally, point BRAWLSTARS_API_BASE at
// https://api.brawlstars.com/v1 and use a key whitelisted for your own IP.
const PROXY = "https://bsproxy.royaleapi.dev/v1";

type ApiPlayer = { tag: string; name: string; trophies: number; brawlers: { id: number; power: number }[] };

/** GET /api/player/:tag -> the player's name, trophies and brawler power levels. Not cached: it runs on connect. */
export async function GET(_req: NextRequest, ctx: RouteContext<"/api/player/[tag]">) {
  const { tag: raw } = await ctx.params;
  const tag = normalizeTag(decodeURIComponent(raw));
  if (!tag) return Response.json({ error: "That isn’t a valid player tag." }, { status: 400 });

  const token = process.env.BRAWLSTARS_API_TOKEN;
  if (!token) return Response.json({ error: "Player lookup isn’t set up on this server yet." }, { status: 503 });

  let res: Response;
  try {
    res = await fetch(`${process.env.BRAWLSTARS_API_BASE ?? PROXY}/players/%23${tag}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    return Response.json({ error: "Couldn’t reach Brawl Stars. Try again in a moment." }, { status: 502 });
  }
  if (res.status === 404) return Response.json({ error: "No player has that tag." }, { status: 404 });
  if (res.status === 429) return Response.json({ error: "Too many lookups right now. Try again in a minute." }, { status: 429 });
  if (!res.ok) return Response.json({ error: "Brawl Stars didn’t answer. Try again in a moment." }, { status: 502 });

  const p = (await res.json()) as ApiPlayer;
  const player: Player = {
    tag: p.tag.replace(/^#/, ""),
    name: p.name,
    trophies: p.trophies,
    brawlers: p.brawlers.map((b) => ({ id: b.id, power: b.power })),
  };
  return Response.json(player);
}
