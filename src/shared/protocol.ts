export type Side = 'red' | 'black';
export type ResultKind = 'ongoing' | 'red_win' | 'black_win' | 'draw';
export type Difficulty = 'beginner' | 'casual' | 'advanced' | 'club' | 'expert';

export interface MoveHistoryEntry {
  move: string;
  check: boolean;
  classification: 'quiet' | 'capture' | 'check' | 'chase';
}
export interface GameResult { kind: ResultKind; reason: string }
export interface PositionSnapshot {
  fen: string;
  sideToMove: Side;
  legalMoves: string[];
  history: MoveHistoryEntry[];
  noCapturePlies: number;
  fullmoveNumber: number;
  naturalLimit: { plies: number; redChecks: number; blackChecks: number };
  repetition: { occurrences: number; thirdOccurrence: boolean };
  result: GameResult;
}
export interface Analysis {
  depth: number;
  nodes: number;
  nps: number;
  scoreCp: number;
  mate: number | null;
  pv: string[];
  backend?: 'pikafish' | 'cc0-teacher' | 'fallback';
  status?: string;
}
export interface EngineResponse<T = unknown> { id: string; ok: boolean; data?: T; error?: string }
export interface SavedGameV1 {
  schemaVersion: 1;
  initialFen: string;
  moves: string[];
  clocksMs: { red: number; black: number };
  settings: { mode: 'ai' | 'local'; humanSide: Side; difficulty: Difficulty };
  savedAt: string;
}
export interface XiangqiBridge {
  request<T>(method: string, params?: Record<string, unknown>): Promise<T>;
  saveGame(game: SavedGameV1): Promise<{ canceled: boolean; path?: string }>;
  openGame(): Promise<{ canceled: boolean; game?: SavedGameV1 }>;
}
