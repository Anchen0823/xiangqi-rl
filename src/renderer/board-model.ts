import type { Side } from '../shared/protocol';

export interface BoardPiece { square: string; code: string; side: Side; label: string }

const labels: Record<string, string> = {
  K: '帅', A: '仕', B: '相', N: '马', R: '车', C: '炮', P: '兵',
  k: '将', a: '士', b: '象', n: '马', r: '车', c: '炮', p: '卒',
};

export function parseFenBoard(fen: string): BoardPiece[] {
  const ranks = fen.split(' ')[0].split('/');
  if (ranks.length !== 10) throw new Error('Invalid Xiangqi FEN');
  const pieces: BoardPiece[] = [];
  ranks.forEach((rankText, fenRank) => {
    let file = 0;
    for (const token of rankText) {
      if (/\d/.test(token)) file += Number(token);
      else {
        const rank = 9 - fenRank;
        pieces.push({
          square: `${String.fromCharCode(97 + file)}${rank}`,
          code: token,
          side: token === token.toUpperCase() ? 'red' : 'black',
          label: labels[token] ?? token,
        });
        file += 1;
      }
    }
    if (file !== 9) throw new Error('Invalid Xiangqi FEN rank');
  });
  return pieces;
}

export function squarePosition(square: string, flipped: boolean): { left: string; top: string } {
  const file = square.charCodeAt(0) - 97;
  const rank = Number(square[1]);
  const displayFile = flipped ? 8 - file : file;
  const displayRank = flipped ? rank : 9 - rank;
  return { left: `${displayFile * 12.5}%`, top: `${displayRank * (100 / 9)}%` };
}

