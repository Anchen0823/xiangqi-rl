import { parseFenBoard, type BoardPiece } from './board-model';
import type { Analysis, PositionSnapshot } from '../shared/protocol';

const chinese = '〇一二三四五六七八九';

/** A UCCI move, e.g. `h2e2`. Anything else is already display text. */
function isCoordinateMove(move: string): boolean {
  return /^[a-i][0-9][a-i][0-9]$/.test(move);
}

function play(pieces: BoardPiece[], move: string): BoardPiece[] {
  const piece = pieces.find((item) => item.square === move.slice(0, 2));
  if (!piece) return pieces;
  return [...pieces.filter((item) => item.square !== move.slice(2) && item !== piece), { ...piece, square: move.slice(2) }];
}

/** Null when this board cannot explain the move; the caller then tries an earlier one. */
function describeMove(pieces: BoardPiece[], move: string): string | null {
  if (!isCoordinateMove(move)) return move;
  const from = move.slice(0, 2), to = move.slice(2);
  const piece = pieces.find((item) => item.square === from);
  if (!piece) return null;
  const red = piece.side === 'red';
  const number = (n: number) => red ? chinese[n] : String(n);
  const file = (square: string) => red ? 106 - square.charCodeAt(0) : square.charCodeAt(0) - 96;
  const rank = (square: string) => Number(square[1]);
  const type = piece.code.toLowerCase();
  const peers = pieces.filter((item) => item.code === piece.code && item.square[0] === from[0])
    .sort((a, b) => (rank(b.square) - rank(a.square)) * (red ? 1 : -1));
  let prefix = piece.label + number(file(from));
  // Advisors/elephants are identified by their source file in conventional notation.
  if (peers.length > 1 && 'rncp'.includes(type)) {
    const index = peers.findIndex((item) => item.square === from);
    const order = peers.length === 2 ? ['前', '后'][index]
      : peers.length === 3 ? ['前', '中', '后'][index] : chinese[index + 1];
    prefix = order + piece.label;
    // Multiple doubled pawn files need the file as well to stay unambiguous.
    if (type === 'p' && pieces.some((item) => item.code === piece.code && item.square[0] !== from[0]
      && pieces.some((other) => other !== item && other.code === item.code && other.square[0] === item.square[0]))) {
      prefix += number(file(from));
    }
  }
  const delta = rank(to) - rank(from);
  const action = delta === 0 ? '平' : delta * (red ? 1 : -1) > 0 ? '进' : '退';
  const destination = delta === 0 || 'nab'.includes(type) ? file(to) : Math.abs(delta);
  return prefix + action + number(destination);
}

/**
 * Renders one move in Chinese notation. `describeMove` reads the moving piece
 * off its origin square, so each candidate board must be the position *before*
 * the move. Boards are ordered newest first: the board the caller is showing is
 * tried first, and when a recommended move belongs to an earlier position the
 * game is rolled back ply by ply until a board still holds that piece. Only a
 * move that no ply explains is passed through unchanged, which surfaces a real
 * bug instead of dressing it up as plausible notation.
 */
function renderFrom(boards: BoardPiece[][], move: string): string {
  return boards.map((pieces) => describeMove(pieces, move)).find((text) => text !== null) ?? move;
}

/** Display only: legality and game adjudication remain with the native engine. */
export function chineseMove(initialFen: string, history: string[], move: string): string {
  if (!isCoordinateMove(move)) return move;
  // prefixes[k] is the board after k of the history's plies, so the newest
  // entry is the position this move is played in.
  const prefixes: BoardPiece[][] = [parseFenBoard(initialFen)];
  for (const played of history) prefixes.push(play(prefixes[prefixes.length - 1], played));
  return renderFrom(prefixes.slice().reverse(), move);
}

export function chineseMoves(initialFen: string, moves: string[]): string[] {
  return moves.map((move, index) => chineseMove(initialFen, moves.slice(0, index), move));
}

/** A recommendation is interpreted only in the exact position the engine searched. */
export function recommendedMove(snapshot: PositionSnapshot | null, analysisFen: string, analysis: Analysis | null): string | undefined {
  const move = analysis?.pv[0];
  if (!snapshot || analysisFen !== snapshot.fen || !move || !snapshot.legalMoves.includes(move)) return undefined;
  // snapshot.fen already includes the entire history; replaying it again can
  // overwrite a different piece now occupying one of the old origin squares.
  return chineseMove(snapshot.fen, [], move);
}
