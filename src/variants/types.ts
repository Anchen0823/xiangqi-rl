/** Versioned experimental rules. This protocol is deliberately separate from standard Xiangqi. */
export type Color = 'red' | 'black';
export type Seat = 0 | 1;
export type Mode = 'custom' | 'jieqi' | 'banqi';
export type Square = number;
export interface Movement {
  directions: [number, number][];
  max: number; // 0 = slide to board edge
  jump?: boolean;
  relative?: boolean;
  blockers?: [number, number][];
  screens?: number;
  region?: 'all' | 'palace' | 'home' | 'crossed';
}
export interface PieceDefinition {
  id: string;
  label: string;
  moves: Movement[];
  captures: Movement[];
}
export interface RuleSet {
  schemaVersion: 1;
  version: 'lab-v1';
  mode: Mode;
  width: number;
  height: number;
  pieces: PieceDefinition[];
  quietLimit: number;
}
export interface Piece {
  id: number;
  color: Color;
  kind: string;
  square: Square;
  hidden: boolean;
  role: string;
}
export interface Scenario {
  schemaVersion: 1;
  id: string;
  name: string;
  rules: RuleSet;
  pieces: Piece[];
  turn: Seat;
  seats: [Color | null, Color | null];
  focusColor?: Color;
}
export type Action = { type: 'move'; from: Square; to: Square } | { type: 'flip'; square: Square };
export interface Capture {
  id: number;
  color: Color;
  kind: string;
  role: string;
  hidden: boolean;
  by: Seat;
}
export interface GameResult { kind: 'ongoing' | 'win' | 'draw'; winner?: Seat; reason: string }
export interface TurnRecord {
  action: Action;
  seat: Seat;
  check: boolean;
  chased: number[];
  revealed?: { id: number; kind: string; color: Color };
  capture?: Capture;
}
export interface GameState {
  scenario: Scenario;
  pieces: Piece[];
  captures: Capture[];
  turn: Seat;
  seats: [Color | null, Color | null];
  quiet: number;
  ply: number;
  result: GameResult;
  history: TurnRecord[];
  keys: string[];
  practice: boolean;
}
export interface VisiblePiece extends Omit<Piece, 'kind' | 'color'> { kind: string | null; color: Color | null }
export interface VisibleCapture extends Omit<Capture, 'kind'> { kind: string | null }
export interface Observation {
  schemaVersion: 1;
  rules: RuleSet;
  rulesHash: string;
  viewer: Seat;
  pieces: VisiblePiece[];
  captures: VisibleCapture[];
  /** Initial inventory is public; individual initial identities/seed are never included. */
  inventory: { color: Color; kind: string; count: number }[];
  turn: Seat;
  seats: [Color | null, Color | null];
  quiet: number;
  ply: number;
  result: GameResult;
  history: Omit<TurnRecord, 'capture'>[];
  keys: string[];
  legalActions: Action[];
}
export interface SearchBudget { nodes: number; seed: number; maxMillis?: number; rollout: number }
export interface SearchResult {
  action: Action | null;
  policy: [number, number][];
  nodes: number;
  simulations: number;
  inferences: number;
  elapsedMs: number;
  status: 'ok' | 'timeout' | 'terminal';
}
export interface ModelManifest {
  schemaVersion: 1;
  rulesHash: string;
  featureVersion: 'lab-features-v1';
  inputSize: number;
  actionSize: number;
  sha256: string;
  training: Record<string, unknown>;
}
export interface SavedVariant {
  schemaVersion: 1;
  format: 'xqlab';
  rulesHash: string;
  scenario: Scenario;
  actions: Action[];
  practice: boolean;
}
export const other = (seat: Seat): Seat => seat === 0 ? 1 : 0;
export const opposite = (color: Color): Color => color === 'red' ? 'black' : 'red';
export const actionKey = (a: Action) => a.type === 'flip' ? `f${a.square}` : `m${a.from}:${a.to}`;
export const actionIndex = (a: Action) => a.type === 'flip' ? 8100 + a.square : a.from * 90 + a.to;
