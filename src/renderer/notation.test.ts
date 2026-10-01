import { expect, it } from 'vitest';
import { chineseMoves } from './notation';

const initial = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';
it('uses each side’s file numbering and replays history', () => {
  expect(chineseMoves(initial, ['h2e2', 'b9c7', 'h0g2', 'a9b9']))
    .toEqual(['炮二平五', '马2进3', '马二进三', '车1平2']);
});
it('distinguishes vertical distance and diagonal destination', () => {
  expect(chineseMoves(initial, ['a0a2', 'c9e7', 'g0e2', 'd9e8', 'f0e1', 'a2a0']))
    .toEqual(['车九进二', '象3进5', '相三进五', '士4进5', '仕四进五', '车九退二']);
});
it('handles front/back pieces from both perspectives', () => {
  const fen = '4k4/9/r8/9/r8/R8/9/R8/9/4K4 w - - 0 1';
  expect(chineseMoves(fen, ['a4b4', 'a5b5', 'a2a3', 'a7a6']))
    .toEqual(['前车平八', '前车平2', '车九进一', '车1进1']);
});
it('handles three stacked pawns and multiple doubled files', () => {
  expect(chineseMoves('4k4/9/P8/P8/P8/9/9/9/9/4K4 w - - 0 1', ['a6b6']))
    .toEqual(['中兵平八']);
  expect(chineseMoves('4k4/9/P1P6/P1P6/9/9/9/9/9/4K4 w - - 0 1', ['a7b7']))
    .toEqual(['前兵九平八']);
});
it('tracks captures and preserves unknown moves without crashing', () => {
  expect(chineseMoves('4k4/9/9/r8/9/R8/9/9/9/4K4 w - - 0 1', ['a4a6', 'a6b6']))
    .toEqual(['车九进二', '车九平八']);
  expect(chineseMoves(initial, ['(none)', 'a5a6'])).toEqual(['(none)', 'a5a6']);
});
