import { expect, it } from 'vitest';
import type { PositionSnapshot } from '../shared/protocol';
import { moveFeedback } from './game-feedback';

const before: PositionSnapshot = {
  fen: '', sideToMove: 'red', legalMoves: ['a0a1'], history: [], noCapturePlies: 0,
  fullmoveNumber: 1, naturalLimit: { plies: 0, redChecks: 0, blackChecks: 0 },
  repetition: { occurrences: 1, thirdOccurrence: false }, result: { kind: 'ongoing', reason: '' },
};
const after = (check = false, capture = false): PositionSnapshot => ({ ...before,
  sideToMove: 'black', history: [{ move: 'a0a1', check, classification: capture ? 'capture' : 'quiet' }],
});
it('distinguishes normal moves, captures and checks', () => {
  expect(moveFeedback(before, after())?.cue).toBe('move');
  expect(moveFeedback(before, after(false, true))?.cue).toBe('capture');
  expect(moveFeedback(before, after(true, true))).toEqual({ cue: 'check', capture: true, square: 'a1' });
});
it('prioritizes checkmate and stalemate over capture/check', () => {
  for (const reason of ['checkmate', 'stalemate']) {
    expect(moveFeedback(before, { ...after(true, true), result: { kind: 'red_win', reason } })?.cue).toBe(reason);
  }
  expect(moveFeedback(before, { ...after(), result: { kind: 'draw', reason: 'natural_limit' } })?.cue).toBe('draw');
});
it('does not replay effects for undo, unchanged snapshots or replaced histories', () => {
  expect(moveFeedback(after(), before)).toBeNull();
  expect(moveFeedback(after(), after())).toBeNull();
  expect(moveFeedback(after(), { ...after(), history: [
    { move: 'b0c2', check: false, classification: 'quiet' },
    { move: 'a9a8', check: false, classification: 'quiet' },
  ] })).toBeNull();
});
