import type { PositionSnapshot } from '../shared/protocol';

// 'select' is a local interaction cue and never comes from a legal move.
export type Cue = 'select' | 'move' | 'capture' | 'check' | 'checkmate' | 'stalemate' | 'win' | 'draw';
export interface MoveFeedback { cue: Cue; capture: boolean; square: string }

export function moveFeedback(before: PositionSnapshot, after: PositionSnapshot): MoveFeedback | null {
  if (before.result.kind !== 'ongoing' || after.history.length !== before.history.length + 1
    || !before.history.every((entry, i) => entry.move === after.history[i].move)) return null;
  const last = after.history.at(-1)!;
  const terminal = after.result.kind !== 'ongoing';
  const cue: Cue = terminal ? after.result.kind === 'draw' ? 'draw'
    : after.result.reason === 'checkmate' ? 'checkmate'
    : after.result.reason === 'stalemate' ? 'stalemate' : 'win'
    : last.check ? 'check' : last.classification === 'capture' ? 'capture' : 'move';
  return { cue, capture: last.classification === 'capture', square: last.move.slice(2) };
}

export const cueTitles: Record<Cue, string> = {
  select: '选子', move: '落子', capture: '吃子', check: '将军', checkmate: '绝杀',
  stalemate: '困毙', win: '胜负已定', draw: '和棋',
};
