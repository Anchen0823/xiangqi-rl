import { parseFenBoard } from './board-model';
import type { Side } from '../shared/protocol';

export const INITIAL_FEN = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';
export const EMPTY_FEN = '9/9/9/9/9/9/9/9/9/9 w - - 0 1';
export const EDITOR_PIECES = ['K', 'A', 'B', 'N', 'R', 'C', 'P', 'k', 'a', 'b', 'n', 'r', 'c', 'p'];

export function serializePosition(board: Map<string, string>, side: Side): string {
  const ranks = Array.from({ length: 10 }, (_, index) => {
    let text = '';
    let empty = 0;
    for (let file = 0; file < 9; file++) {
      const code = board.get(`${String.fromCharCode(97 + file)}${9 - index}`);
      if (!code) { empty++; continue; }
      if (empty) { text += empty; empty = 0; }
      text += code;
    }
    return text + (empty || '');
  });
  return `${ranks.join('/')} ${side === 'red' ? 'w' : 'b'} - - 0 1`;
}

export function editSquare(fen: string, square: string, code: string | null, source?: string | null): string {
  const board = new Map(parseFenBoard(fen).map((piece) => [piece.square, piece.code]));
  if (source) board.delete(source);
  if (code) board.set(square, code);
  else board.delete(square);
  return serializePosition(board, fen.split(' ')[1] === 'b' ? 'black' : 'red');
}

export function positionError(fen: string): string | null {
  const pieces = parseFenBoard(fen);
  const limits: Record<string, number> = { k: 1, a: 2, b: 2, n: 2, r: 2, c: 2, p: 5 };
  for (const code of EDITOR_PIECES) {
    const count = pieces.filter((piece) => piece.code === code).length;
    const side = code === code.toUpperCase() ? '红方' : '黑方';
    if (code.toLowerCase() === 'k' && count !== 1) return `${side}必须有且只有一个将帅。`;
    if (count > limits[code.toLowerCase()]) return `${side}棋子数量超出初始配置，请删去多余棋子。`;
  }
  for (const piece of pieces) {
    const file = piece.square.charCodeAt(0) - 97;
    const rank = Number(piece.square[1]);
    const red = piece.side === 'red';
    const ownRank = red ? rank : 9 - rank;
    const code = piece.code.toLowerCase();
    if (code === 'k' && (file < 3 || file > 5 || ownRank > 2)) return '将帅必须位于各自九宫内。';
    if (code === 'a' && !['30', '50', '41', '32', '52'].includes(`${file}${ownRank}`)) return '士仕必须位于各自九宫的斜线交点。';
    if (code === 'b' && !['20', '60', '02', '42', '82', '24', '64'].includes(`${file}${ownRank}`)) return '象相必须位于己方合法象位，不能过河。';
    if (code === 'p' && (ownRank < 3 || (ownRank < 5 && file % 2 !== 0))) return '兵卒不能后退到初始线后，未过河时须在兵卒路上。';
  }
  const redKing = pieces.find((piece) => piece.code === 'K')!;
  const blackKing = pieces.find((piece) => piece.code === 'k')!;
  if (redKing.square[0] === blackKing.square[0]) {
    const file = redKing.square[0];
    const lower = Number(redKing.square[1]);
    const upper = Number(blackKing.square[1]);
    if (!pieces.some((piece) => piece.square[0] === file && Number(piece.square[1]) > lower && Number(piece.square[1]) < upper)) return '将帅不能在同一路上直接照面。';
  }
  return null;
}
