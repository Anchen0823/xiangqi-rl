import { describe, expect, it } from 'vitest';
import { parseFenBoard, squarePosition } from './board-model';

describe('board helpers', () => {
  it('parses the standard setup', () => {
    const pieces = parseFenBoard('rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1');
    expect(pieces).toHaveLength(32);
    expect(pieces.find((piece) => piece.square === 'e0')?.label).toBe('帅');
    expect(pieces.find((piece) => piece.square === 'e9')?.label).toBe('将');
  });
  it('flips coordinates', () => {
    expect(squarePosition('a0', false)).toEqual({ left: '0%', top: '100%' });
    expect(squarePosition('a0', true)).toEqual({ left: '100%', top: '0%' });
  });
});
