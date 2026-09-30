import { expect, it } from 'vitest';
import { chineseMove } from './notation';

// Kept as a scratch-free regression check for the reported display bug: the
// panel showed the engine's raw UCCI (`h7i7`) instead of 中象记谱法.
it('names a recommended move in Chinese notation', () => {
  const fen = 'rnbakab1r/9/1c4nc1/p1p1p1p1p/9/2P6/P3P1P1P/4C2C1/9/RNBAKABNR b - - 3 2';
  expect(chineseMove(fen, [], 'h7i7')).toBe('炮8平9');
});
