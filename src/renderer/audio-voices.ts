import type { Cue } from './game-feedback';

// Pure voice planning: no Web Audio types, so the sound design stays unit
// testable and the renderer in game-audio.ts only has to schedule nodes.
export type VoiceKind = 'noise' | 'modal' | 'thump' | 'bell';

export interface AudioVoice {
  kind: VoiceKind;
  /** Base frequency in Hz. Ignored by 'noise'. */
  freq: number;
  /** Inharmonic partial ratios. Absent for 'noise' and 'thump'. */
  partials?: readonly number[];
  gain: number;
  attack: number;
  decay: number;
  /** Seconds after the cue starts. */
  delay: number;
  /** -1 hard left to 1 hard right. */
  pan: number;
  /** Band-pass centre in Hz; only 'noise' uses it. */
  colour?: number;
  /** Level sent to the shared ambience bus; 0 stays fully dry. */
  space: number;
}

export interface CueContext {
  /** FEN piece code of the piece that moved or was picked up. */
  piece?: string;
  /** Board square, used for stereo placement. */
  square?: string;
  /** Monotonic move counter, keeps repeated moves from sounding identical. */
  step?: number;
}

// A struck wooden piece rings a little sharp and a little hollow, so the
// partials are deliberately inharmonic rather than a plain harmonic series.
const WOOD = [1, 2.37, 4.15, 6.63] as const;
// Bronze bell: hum, prime, minor third, nominal, quint and a high shimmer.
const BELL = [0.5, 1, 2.02, 2.98, 4.16, 5.43] as const;
const PARTIAL_GAIN = [1, 0.52, 0.3, 0.18, 0.11, 0.07];

// Heavier pieces land lower and ring longer than a foot soldier.
const PIECE_WEIGHT: Record<string, number> = {
  K: 0.82, R: 0.88, C: 0.95, N: 1, A: 1.06, B: 1.1, P: 1.16,
};

export function pieceWeight(code?: string): number {
  if (!code) return 1;
  return PIECE_WEIGHT[code.toUpperCase()] ?? 1;
}

/** Maps the board file a-i onto a narrow stereo field. */
export function squarePan(square?: string): number {
  if (!square) return 0;
  const file = square.charCodeAt(0) - 97;
  if (file < 0 || file > 8) return 0;
  return ((file - 4) / 4) * 0.6;
}

function mulberry32(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashSeed(cue: Cue, context: CueContext): number {
  let hash = 2166136261;
  const push = (text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
  };
  push(cue);
  push(context.piece ?? '');
  push(context.square ?? '');
  push(String(context.step ?? 0));
  return hash >>> 0;
}

const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(high, value));

interface PlanInput {
  weight: number;
  pan: number;
  onset: number;
}

const planMove = ({ weight, pan, onset }: PlanInput): AudioVoice[] => [
  { kind: 'noise', freq: 0, gain: 0.34, attack: 0.001, decay: 0.018, delay: onset, pan, colour: 2600, space: 0.05 },
  { kind: 'modal', freq: 470 * weight, partials: WOOD, gain: 0.5, attack: 0.002, decay: 0.115, delay: onset + 0.001, pan, colour: 0, space: 0.1 },
  { kind: 'thump', freq: 132 * weight, gain: 0.3, attack: 0.003, decay: 0.09, delay: onset, pan, colour: 0, space: 0.05 },
];

const planCapture = ({ weight, pan, onset }: PlanInput): AudioVoice[] => [
  { kind: 'noise', freq: 0, gain: 0.6, attack: 0.0008, decay: 0.03, delay: onset, pan, colour: 3400, space: 0.12 },
  { kind: 'modal', freq: 400 * weight, partials: WOOD, gain: 0.62, attack: 0.002, decay: 0.19, delay: onset + 0.002, pan, colour: 0, space: 0.16 },
  { kind: 'modal', freq: 400 * weight * 2.6, partials: [1, 1.9], gain: 0.16, attack: 0.001, decay: 0.07, delay: onset + 0.004, pan, colour: 0, space: 0.1 },
  { kind: 'thump', freq: 104 * weight, gain: 0.62, attack: 0.003, decay: 0.16, delay: onset, pan, colour: 0, space: 0.12 },
];

const planCheck = ({ weight, pan, onset }: PlanInput): AudioVoice[] => [
  { kind: 'noise', freq: 0, gain: 0.3, attack: 0.001, decay: 0.016, delay: onset, pan, colour: 2800, space: 0.05 },
  { kind: 'modal', freq: 500 * weight, partials: WOOD, gain: 0.42, attack: 0.002, decay: 0.1, delay: onset + 0.001, pan, colour: 0, space: 0.1 },
  { kind: 'bell', freq: 700, partials: BELL, gain: 0.34, attack: 0.004, decay: 1.05, delay: onset + 0.035, pan: -pan * 0.4, space: 0.38 },
];

const planCheckmate = ({ weight, pan, onset }: PlanInput): AudioVoice[] => {
  const knock = (delay: number, freq: number, gain: number): AudioVoice[] => [
    { kind: 'noise', freq: 0, gain: gain * 0.6, attack: 0.001, decay: 0.02, delay: onset + delay, pan, colour: 3000, space: 0.06 },
    { kind: 'modal', freq: freq * weight, partials: WOOD, gain, attack: 0.002, decay: 0.13, delay: onset + delay + 0.001, pan, colour: 0, space: 0.12 },
  ];
  return [
    ...knock(0, 470, 0.45),
    ...knock(0.1, 545, 0.52),
    ...knock(0.2, 630, 0.6),
    { kind: 'bell', freq: 660, partials: BELL, gain: 0.4, attack: 0.005, decay: 1.6, delay: onset + 0.32, pan: -pan * 0.3, space: 0.5 },
    { kind: 'thump', freq: 96, gain: 0.7, attack: 0.004, decay: 0.3, delay: onset + 0.32, pan, colour: 0, space: 0.2 },
  ];
};

// Muted and low: the board is blocked rather than struck.
const planStalemate = ({ weight, pan, onset }: PlanInput): AudioVoice[] => [
  { kind: 'noise', freq: 0, gain: 0.18, attack: 0.002, decay: 0.03, delay: onset, pan, colour: 900, space: 0.08 },
  { kind: 'modal', freq: 300 * weight, partials: [1, 1.9], gain: 0.3, attack: 0.004, decay: 0.22, delay: onset + 0.002, pan, colour: 0, space: 0.1 },
  { kind: 'thump', freq: 78, gain: 0.7, attack: 0.005, decay: 0.35, delay: onset, pan, colour: 0, space: 0.1 },
];

const planDraw = ({ pan, onset }: PlanInput): AudioVoice[] => [
  { kind: 'modal', freq: 394, partials: [1, 2.01, 3.02], gain: 0.34, attack: 0.006, decay: 0.42, delay: onset, pan: -pan * 0.3, colour: 0, space: 0.22 },
  { kind: 'modal', freq: 330, partials: [1, 2.01, 3.02], gain: 0.3, attack: 0.006, decay: 0.6, delay: onset + 0.18, pan: pan * 0.3, colour: 0, space: 0.26 },
];

const planWin = ({ pan, onset }: PlanInput): AudioVoice[] => {
  const arpeggio = [392, 494, 587, 784];
  const voices = arpeggio.flatMap((freq, index): AudioVoice[] => [
    { kind: 'modal', freq, partials: [1, 2.01, 3.04], gain: 0.3, attack: 0.005, decay: 0.3, delay: onset + index * 0.11, pan: (index % 2 ? 1 : -1) * pan * 0.5, colour: 0, space: 0.24 },
  ]);
  return [
    ...voices,
    { kind: 'bell', freq: 784, partials: BELL, gain: 0.3, attack: 0.005, decay: 1.4, delay: onset + 0.46, pan, colour: 0, space: 0.42 },
  ];
};

// Picking a piece up is a light tick, far quieter than placing one.
const planSelect = ({ weight, pan, onset }: PlanInput): AudioVoice[] => [
  { kind: 'noise', freq: 0, gain: 0.2, attack: 0.0008, decay: 0.008, delay: onset, pan, colour: 4200, space: 0.03 },
  { kind: 'modal', freq: 900 * weight, partials: [1, 2.4], gain: 0.24, attack: 0.001, decay: 0.05, delay: onset + 0.001, pan, colour: 0, space: 0.04 },
];

const PLANNERS: Record<Cue, (input: PlanInput) => AudioVoice[]> = {
  move: planMove,
  capture: planCapture,
  check: planCheck,
  checkmate: planCheckmate,
  stalemate: planStalemate,
  draw: planDraw,
  win: planWin,
  select: planSelect,
};

/**
 * Builds the voice list for a cue. Repeated moves differ because the plan is
 * seeded from the cue, piece, square and move counter, then jittered per voice.
 */
export function planCue(cue: Cue, context: CueContext = {}): AudioVoice[] {
  const random = mulberry32(hashSeed(cue, context));
  const jitter = (amount: number) => (random() * 2 - 1) * amount;
  const input: PlanInput = {
    weight: pieceWeight(context.piece),
    pan: squarePan(context.square),
    onset: random() * 0.008,
  };
  return PLANNERS[cue](input).map((voice) => ({
    ...voice,
    freq: voice.freq * (1 + jitter(0.045)),
    gain: voice.gain * (1 + jitter(0.1)),
    decay: voice.decay * (1 + jitter(0.14)),
    delay: Math.max(0, voice.delay + jitter(0.004)),
    pan: clamp(voice.pan + jitter(0.08), -1, 1),
    colour: voice.colour ? voice.colour * (1 + jitter(0.12)) : undefined,
  }));
}
