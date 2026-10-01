import { describe, expect, it } from 'vitest';
import { chineseMove, chineseMoves } from './notation';

const initial = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';

describe('recommended move notation', () => {
  it('names the engine move from the position it was searched in', () => {
    // The panel's own FEN after 炮八平五 马8进7 兵七进一: the h-file cannon is
    // still home, so the engine's h7i7 is 炮8平9.
    const fen = 'rnbakab1r/9/1c4nc1/p1p1p1p1p/9/2P6/P3P1P1P/4C2C1/9/RNBAKABNR b - - 3 2';
    expect(chineseMove(fen, [], 'h7i7')).toBe('炮8平9');
  });

  it('never shows raw coordinates when the board has already moved on', () => {
    // The reported bug: the recommendation belongs to the position above, but
    // it is rendered against the initial board, where h7 holds a black cannon
    // of a different game. Rolling back the history still has to name it.
    const history = ['b2e2', 'h9g7', 'c3c4'];
    const after = 'rnbakab1r/9/1c4nc1/p1p1p1p1p/9/2P6/P3P1P1P/4C2C1/9/RNBAKABNR b - - 3 2';
    expect(chineseMove(initial, history.concat('h7i7'), 'h7i7')).not.toMatch(/^[a-i][0-9][a-i][0-9]$/);
    expect(chineseMove(initial, history, 'h7i7')).toBe('炮8平9');
    expect(after).toBe('rnbakab1r/9/1c4nc1/p1p1p1p1p/9/2P6/P3P1P1P/4C2C1/9/RNBAKABNR b - - 3 2');
  });

  it('passes through a move that is not a coordinate move', () => {
    expect(chineseMove(initial, [], '(none)')).toBe('(none)');
    expect(chineseMoves(initial, ['(none)', 'a5a6'])).toEqual(['(none)', 'a5a6']);
  });
});

describe('history notation', () => {
  it('keeps rendering every played move in Chinese notation', () => {
    const moves = ['b2e2', 'h9g7', 'c3c4', 'h7i7'];
    expect(chineseMoves(initial, moves)).toEqual(['炮八平五', '马8进7', '兵七进一', '炮8平9']);
  });
});
