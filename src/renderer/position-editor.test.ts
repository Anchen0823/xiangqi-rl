import { describe, expect, it } from 'vitest';
import { parseFenBoard } from './board-model';
import { editSquare, EMPTY_FEN, INITIAL_FEN, positionError, serializePosition } from './position-editor';

describe('position editor', () => {
  it('round-trips both viewing orientations through canonical FEN coordinates', () => {
    const board = new Map(parseFenBoard(INITIAL_FEN).map((piece) => [piece.square, piece.code]));
    expect(serializePosition(board, 'red')).toBe(INITIAL_FEN);
    expect(serializePosition(board, 'black')).toBe(INITIAL_FEN.replace(' w ', ' b '));
  });
  it('moves, replaces and removes pieces without changing the side to move', () => {
    const fen = INITIAL_FEN.replace(' w ', ' b ');
    const moved = editSquare(fen, 'e2', 'C', 'h2');
    expect(parseFenBoard(moved).find((piece) => piece.square === 'h2')).toBeUndefined();
    expect(parseFenBoard(moved).find((piece) => piece.square === 'e2')?.code).toBe('C');
    expect(moved.split(' ')[1]).toBe('b');
    expect(parseFenBoard(editSquare(moved, 'e2', 'c'))).toHaveLength(32);
    expect(parseFenBoard(editSquare(moved, 'e2', null))).toHaveLength(31);
  });
  it('accepts standard and legal sparse positions', () => {
    expect(positionError(INITIAL_FEN)).toBeNull();
    expect(positionError('4k4/9/9/9/4p4/9/9/9/9/4K4 w - - 0 1')).toBeNull();
  });
  it('rejects missing or duplicate kings, excess pieces and facing kings', () => {
    expect(positionError(EMPTY_FEN)).toContain('将帅');
    expect(positionError(editSquare(INITIAL_FEN, 'd1', 'K'))).toContain('将帅');
    expect(positionError(editSquare(INITIAL_FEN, 'e2', 'R'))).toContain('数量');
    expect(positionError('4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1')).toContain('照面');
  });
  it('rejects unreachable palace, elephant and pawn placements', () => {
    expect(positionError(editSquare(INITIAL_FEN, 'a1', 'K', 'e0'))).toContain('九宫');
    expect(positionError(editSquare(INITIAL_FEN, 'e0', 'A', 'd0'))).toContain('将帅');
    expect(positionError(editSquare(INITIAL_FEN, 'd1', 'A', 'd0'))).toContain('斜线');
    expect(positionError(editSquare(INITIAL_FEN, 'c6', 'B', 'c0'))).toContain('象位');
    expect(positionError(editSquare(INITIAL_FEN, 'b3', 'P', 'a3'))).toContain('兵卒');
  });
});
