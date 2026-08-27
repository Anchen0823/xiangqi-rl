import type { Analysis, PositionSnapshot, SavedGameV1, XiangqiBridge } from '../shared/protocol';

const INITIAL_FEN = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';

function initialSnapshot(): PositionSnapshot {
  return {
    fen: INITIAL_FEN,
    sideToMove: 'red',
    legalMoves: [],
    history: [],
    noCapturePlies: 0,
    fullmoveNumber: 1,
    naturalLimit: { plies: 0, redChecks: 0, blackChecks: 0 },
    repetition: { occurrences: 1, thirdOccurrence: false },
    result: { kind: 'ongoing', reason: '' },
  };
}

/** Browser-only bridge used by Vite previews and visual regression checks. */
export function installPreviewBridge(): void {
  if (window.xiangqi) return;
  let snapshot = initialSnapshot();
  const bridge: XiangqiBridge = {
    async request<T>(method: string): Promise<T> {
      if (method === 'newGame') snapshot = initialSnapshot();
      if (method === 'analyze') {
        return {
          depth: 12, nodes: 184_320, nps: 728_400, scoreCp: 18,
          mate: null, pv: ['h2e2', 'h7e7', 'b2b6'],
        } satisfies Analysis as T;
      }
      if (method === 'stop') return undefined as T;
      return structuredClone(snapshot) as T;
    },
    async saveGame(_game: SavedGameV1) { return { canceled: true }; },
    async openGame() { return { canceled: true }; },
  };
  Object.defineProperty(window, 'xiangqi', { value: bridge, configurable: true });
}
