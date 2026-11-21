// Port of src/mira/engine/model.py: win scoring and pick probabilities from model.json.
// Keep in step with the Python reference; tests/parity checks the two agree.

export type ModelJson = {
  format: number;
  trained_at: string;
  data_window: [string, string];
  n_matches: number;
  brawlers: { id: number; name: string }[];
  modes: string[];
  maps: { mode: string; map: string }[];
  win_model: {
    global: number[];
    mode: number[][];
    map: number[][];
    synergy: [number, number, number][];
    synergy_mode: [number, number, number, number][];
    matchup: [number, number, number][];
    matchup_mode: [number, number, number, number][];
    tier?: number[][]; // [B][n_tiers]
    tier_mode?: number[][][]; // [B][n_tiers][n_modes]
  };
  tiers?: string[];
  default_tier?: number;
  pick_model: {
    alpha: number;
    beta: number;
    log_base: number[][];
    log_base_tier?: number[][][]; // [n_tiers][B][n_maps]
    ally_lift: [number, number, number][];
    enemy_lift: [number, number, number][];
  };
  games?: { brawler: number[]; brawler_map: number[][] };
  /** How the search ranks our own candidates (Model.adjust). Absent in older files: off. */
  ranking?: { kappa: number; gamma: number; rho?: number; ban_lambda?: number; strength_sd: number[][][] }; // sd: [n_tiers][B][n_maps]
  /** Pro esports drafts (Liquipedia): log pick share and ban rate, [B][n_maps]. */
  pro?: { log_pick: number[][]; ban: number[][]; since: string; until: string; n_maps: number };
  patches?: { date: string; changes: Record<string, string> }[];
};

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

export class Model {
  readonly names: string[];
  readonly ids: number[];
  readonly B: number;
  readonly maps: { mode: string; map: string }[];
  readonly modes: string[];
  private readonly modeOfMap: number[];
  private readonly g: number[];
  private readonly sMode: number[][];
  private readonly sMap: number[][];
  private readonly sTier?: number[][];
  private readonly sTierMode?: number[][][];
  /** Rank tier the draft is played at (index into data.tiers). */
  readonly tier: number;
  readonly tiers: string[];
  // Pair tables as flat arrays indexed lo*B+hi (and *nModes+mode): faster than Maps in the search.
  private readonly syn: Float64Array;
  private readonly synMode: Float64Array;
  private readonly mu: Float64Array;
  private readonly muMode: Float64Array;
  private readonly ally: Float64Array;
  private readonly enemy: Float64Array;
  readonly alpha: number;
  readonly beta: number;
  private readonly logBase: number[][];
  private readonly games?: { brawler: number[]; brawler_map: number[][] };
  readonly kappa: number;
  readonly gamma: number;
  private readonly sd?: number[][];
  readonly rho: number;
  readonly banLambda: number;
  private readonly proLogPick?: number[][];
  private readonly proBan?: number[][];

  constructor(
    readonly data: ModelJson,
    tier?: number,
  ) {
    this.tiers = data.tiers ?? [];
    this.tier = tier ?? data.default_tier ?? 0;
    this.names = data.brawlers.map((b) => b.name);
    this.ids = data.brawlers.map((b) => b.id);
    this.B = this.names.length;
    this.maps = data.maps;
    this.modes = data.modes;
    this.modeOfMap = data.maps.map((m) => data.modes.indexOf(m.mode));
    const w = data.win_model;
    this.g = w.global;
    this.sMode = w.mode;
    this.sMap = w.map;
    this.sTier = w.tier;
    this.sTierMode = w.tier_mode;
    const B = this.B;
    const nm = this.modes.length;
    this.syn = new Float64Array(B * B);
    this.synMode = new Float64Array(B * B * nm);
    this.mu = new Float64Array(B * B);
    this.muMode = new Float64Array(B * B * nm);
    for (const [i, j, v] of w.synergy) this.syn[i * B + j] = v;
    for (const [i, j, k, v] of w.synergy_mode) this.synMode[(i * B + j) * nm + k] = v;
    for (const [i, j, v] of w.matchup) this.mu[i * B + j] = v;
    for (const [i, j, k, v] of w.matchup_mode) this.muMode[(i * B + j) * nm + k] = v;
    const p = data.pick_model;
    this.alpha = p.alpha;
    this.beta = p.beta;
    this.logBase = p.log_base_tier?.[this.tier] ?? p.log_base;
    this.ally = new Float64Array(B * B);
    this.enemy = new Float64Array(B * B);
    for (const [i, j, v] of p.ally_lift) this.ally[i * B + j] = this.ally[j * B + i] = v;
    for (const [i, j, v] of p.enemy_lift) this.enemy[i * B + j] = this.enemy[j * B + i] = v;
    this.games = data.games;
    this.kappa = data.ranking?.kappa ?? 0;
    this.gamma = data.ranking?.gamma ?? 0;
    this.sd = data.ranking?.strength_sd?.[this.tier];
    this.proLogPick = data.pro?.log_pick;
    this.proBan = data.pro?.ban;
    this.rho = this.proLogPick ? (data.ranking?.rho ?? 0) : 0;
    this.banLambda = this.proBan ? (data.ranking?.ban_lambda ?? 0) : 0;
  }

  brawler(name: string): number {
    const key = norm(name);
    const exact = this.names.findIndex((n) => norm(n) === key);
    if (exact >= 0) return exact;
    const hits = this.names.flatMap((n, i) => (norm(n).startsWith(key) ? [i] : []));
    if (hits.length === 1) return hits[0];
    throw new Error(`unknown brawler ${name}`);
  }

  map(name: string): number {
    const key = norm(name);
    let hits = this.maps.flatMap((m, i) => (norm(m.map) === key ? [i] : []));
    if (!hits.length) hits = this.maps.flatMap((m, i) => (norm(m.map).startsWith(key) ? [i] : []));
    if (hits.length === 1) return hits[0];
    throw new Error(`unknown or ambiguous map ${name}`);
  }

  // -- win model --------------------------------------------------------------

  strength(b: number, mp: number): number {
    const k = this.modeOfMap[mp];
    let s = this.g[b] + this.sMode[b][k] + this.sMap[b][mp];
    if (this.sTier && this.sTierMode) s += this.sTier[b][this.tier] + this.sTierMode[b][this.tier][k];
    return s;
  }

  /** The same model, drafting at another rank tier. */
  withTier(tier: number): Model {
    return tier === this.tier ? this : new Model(this.data, tier);
  }

  synergy(a: number, b: number, mp: number): number {
    const [i, j] = a < b ? [a, b] : [b, a];
    const k = this.modeOfMap[mp];
    const ij = i * this.B + j;
    return this.syn[ij] + this.synMode[ij * this.modes.length + k];
  }

  /** Edge of a over b (antisymmetric). */
  matchup(a: number, b: number, mp: number): number {
    if (a === b) return 0;
    const [i, j] = a < b ? [a, b] : [b, a];
    const k = this.modeOfMap[mp];
    const ij = i * this.B + j;
    const v = this.mu[ij] + this.muMode[ij * this.modes.length + k];
    return a < b ? v : -v;
  }

  teamScore(team: readonly number[], mp: number): number {
    let s = 0;
    for (const b of team) s += this.strength(b, mp);
    for (let x = 0; x < team.length; x++)
      for (let y = x + 1; y < team.length; y++) s += this.synergy(team[x], team[y], mp);
    return s;
  }

  /** Works on partial teams too (missing picks contribute 0). */
  logit(ours: readonly number[], theirs: readonly number[], mp: number): number {
    let s = this.teamScore(ours, mp) - this.teamScore(theirs, mp);
    for (const a of ours) for (const b of theirs) s += this.matchup(a, b, mp);
    return s;
  }

  winProb(ours: readonly number[], theirs: readonly number[], mp: number): number {
    return 1 / (1 + Math.exp(-this.logit(ours, theirs, mp)));
  }

  /** Change in our logit from adding b to our team. */
  gain(b: number, ours: readonly number[], theirs: readonly number[], mp: number): number {
    let s = this.strength(b, mp);
    for (const a of ours) s += this.synergy(b, a, mp);
    for (const e of theirs) s += this.matchup(b, e, mp);
    return s;
  }

  /** Standard error of strength(b, mp): wide for brawlers with few games on the map. */
  sdOf(b: number, mp: number): number {
    return this.sd ? this.sd[b][mp] : 0;
  }

  /**
   * Logit-scale bonus used only to rank and choose our picks, never in a reported win chance:
   * -kappa * sd reads a noisy estimate pessimistically (so the fewest-games brawler doesn't top the
   * list on noise), +gamma * log pick rate counts what Masters players actually pick on the map.
   */
  adjust(b: number, mp: number): number {
    let a = this.kappa ? -this.kappa * this.sdOf(b, mp) : 0;
    if (this.gamma) a += this.gamma * this.logBase[b][mp];
    if (this.rho) a += this.rho * this.proLogPick![b][mp];
    return a;
  }

  /** Share of recent pro maps where b was banned on this map (shrunk toward the mode); 0 without pro data. */
  proBanRate(b: number, mp: number): number {
    return this.proBan ? this.proBan[b][mp] : 0;
  }

  // -- pick model -------------------------------------------------------------

  /** P(next pick = b) for the side owning `allies`, as a typical Masters player. */
  pickProbs(allies: readonly number[], enemies: readonly number[], unavailable: ReadonlySet<number>, mp: number): Map<number, number> {
    const scores = new Map<number, number>();
    let top = -Infinity;
    for (let b = 0; b < this.B; b++) {
      if (unavailable.has(b)) continue;
      let s = this.logBase[b][mp];
      for (const a of allies) s += this.alpha * this.ally[b * this.B + a];
      for (const e of enemies) s += this.beta * this.enemy[b * this.B + e];
      scores.set(b, s);
      if (s > top) top = s;
    }
    let z = 0;
    for (const [b, s] of scores) {
      const e = Math.exp(s - top);
      scores.set(b, e);
      z += e;
    }
    for (const [b, e] of scores) scores.set(b, e / z);
    return scores;
  }

  gamesOnMap(b: number, mp: number): number {
    return this.games?.brawler_map[b]?.[mp] ?? 0;
  }

  /** Brawlers changed in the latest patch, for the "recalibrating" badge. */
  recentlyChanged(): Map<string, string> {
    const latest = this.data.patches?.at(-1);
    return new Map(Object.entries(latest?.changes ?? {}));
  }
}
