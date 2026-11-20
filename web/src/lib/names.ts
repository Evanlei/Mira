/** API names are uppercase ("EL PRIMO", "MR. P", "8-BIT"); show them in title case. */
export function displayName(name: string): string {
  return name.toLowerCase().replace(/(^|[\s\-.])([a-z])/g, (_, sep: string, ch: string) => sep + ch.toUpperCase());
}

/** "gemGrab" -> "Gem Grab", "brawlBall" -> "Brawl Ball". */
export function displayMode(mode: string): string {
  const spaced = mode.replace(/([a-z])([A-Z])/g, "$1 $2");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function initials(name: string): string {
  const parts = displayName(name).split(/[\s\-.]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase();
}

/** Stable hue per brawler id, so an avatar keeps its color everywhere. */
export function hue(id: number): number {
  return (id * 137.508) % 360;
}

/** Change in win chance as percentage points: "+1.2", "−0.4", or "≈0" when it rounds to nothing. */
export function gainPts(gain: number): string {
  const v = gain * 100;
  if (Math.abs(v) < 0.05) return "≈0";
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`;
}

export function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

export function search(name: string, query: string): boolean {
  const n = name.toLowerCase().replace(/[^a-z0-9]/g, "");
  const q = query.toLowerCase().replace(/[^a-z0-9]/g, "");
  return n.includes(q);
}
