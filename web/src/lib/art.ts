// Game art downloaded by scripts/fetch_art.py into public/art (art © Supercell, via Brawlify).
import manifest from "./art.json";

import { displayMode } from "./names";

const portraits = new Set<number>(manifest.brawlers);
const modes = manifest.modes as Record<string, { name: string; color: string | null; icon: string }>;
const maps = manifest.maps as Record<string, string>;

export const ART_CREDIT = manifest.credit;

export function portrait(id: number): string | null {
  return portraits.has(id) ? `/art/brawlers/${id}.png` : null;
}

export function mapImage(mode: string, map: string): string | null {
  return maps[`${mode}|${map}`] ?? null;
}

export function modeInfo(mode: string): { name: string; color: string; icon: string | null } {
  const m = modes[mode];
  return { name: m?.name ?? displayMode(mode), color: m?.color ?? "#9ab1fd", icon: m?.icon ?? null };
}
