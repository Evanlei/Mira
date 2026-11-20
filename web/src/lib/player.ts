// A Brawl Stars player, as the site keeps it: the tag the player connected and which brawlers they
// have at each power level. Shared by the /api/player route and the browser.

export type Player = {
  /** Without the leading "#". */
  tag: string;
  name: string;
  trophies: number;
  /** Every brawler the player owns, by game id, with its power level (1-11). */
  brawlers: { id: number; power: number }[];
};

/** The level a brawler must reach to count as "ready" for Ranked drafts. */
export const READY_POWER = 11;

// Supercell tags only use these characters; people often type O for 0.
const TAG = /^[0289PYLQGRJCUV]{3,14}$/;

/** "#abc 123" -> "ABC123", or null if it can't be a player tag. */
export function normalizeTag(raw: string): string | null {
  const t = raw.trim().toUpperCase().replace(/^#/, "").replace(/\s+/g, "").replace(/O/g, "0");
  return TAG.test(t) ? t : null;
}
