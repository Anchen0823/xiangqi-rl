import { expect, it } from 'vitest';
import { pieceWeight, planCue, squarePan, type AudioVoice } from './audio-voices';
import type { Cue } from './game-feedback';

const cues: Cue[] = ['select', 'move', 'capture', 'check', 'checkmate', 'stalemate', 'draw', 'win'];

const all = cues.flatMap((cue) => planCue(cue, { step: 0 }));

it('produces renderable voices with safe scheduling values', () => {
  expect(all.length).toBeGreaterThan(0);
  for (const voice of all) {
    expect(voice.gain).toBeGreaterThan(0);
    expect(voice.attack).toBeGreaterThanOrEqual(0);
    expect(voice.decay).toBeGreaterThan(0);
    expect(voice.delay).toBeGreaterThanOrEqual(0);
    expect(Math.abs(voice.pan)).toBeLessThanOrEqual(1);
    expect(Number.isFinite(voice.freq)).toBe(true);
    // Only the noise transient is band-limited; pitched voices leave it unset.
    if (voice.kind === 'noise') expect(voice.colour ?? 0).toBeGreaterThan(0);
    else expect(voice.colour).toBeUndefined();
    // Exponential ramps are undefined at zero, so decay must stay above it.
    if (voice.kind === 'modal' || voice.kind === 'bell') {
      expect(voice.partials?.length ?? 0).toBeGreaterThan(0);
      expect(voice.freq).toBeGreaterThan(0);
    }
  }
});

it('varies repeated moves instead of replaying one identical sound', () => {
  const signature = (voices: AudioVoice[]) => voices.map((v) => `${v.kind}:${v.freq.toFixed(2)}:${v.gain.toFixed(3)}`).join('|');
  const steps = Array.from({ length: 8 }, (_, step) => signature(planCue('move', { step })));
  expect(new Set(steps).size).toBe(steps.length);
  // Same inputs must still be reproducible, otherwise tests cannot pin a cue.
  expect(signature(planCue('move', { step: 3 }))).toBe(signature(planCue('move', { step: 3 })));
});

it('keeps variation inside a subtle band around the base tone', () => {
  for (let step = 0; step < 12; step += 1) {
    for (const voice of planCue('move', { step })) {
      if (voice.kind !== 'modal') continue;
      expect(voice.freq).toBeGreaterThan(470 * 0.9);
      expect(voice.freq).toBeLessThan(470 * 1.1);
    }
  }
});

it('makes a capture louder and lower than a quiet move', () => {
  const peak = (voices: AudioVoice[]) => Math.max(...voices.map((v) => v.gain));
  const base = (voices: AudioVoice[]) => Math.min(...voices.filter((v) => v.kind === 'modal').map((v) => v.freq));
  expect(peak(planCue('capture', { step: 0 }))).toBeGreaterThan(peak(planCue('move', { step: 0 })));
  expect(base(planCue('capture', { step: 0 }))).toBeLessThan(base(planCue('move', { step: 0 })));
});

it('rings a bell for check and gives checkmate the longest decay', () => {
  expect(planCue('check', { step: 0 }).some((v) => v.kind === 'bell')).toBe(true);
  const longest = (cue: Cue) => Math.max(...planCue(cue, { step: 0 }).map((v) => v.decay));
  expect(longest('checkmate')).toBeGreaterThan(longest('check'));
  expect(longest('checkmate')).toBeGreaterThan(longest('move'));
  // Picking up a piece stays far quieter than placing one.
  expect(longest('select')).toBeLessThan(longest('move'));
});

it('weights heavy pieces lower and places the sound by board file', () => {
  expect(pieceWeight('K')).toBeLessThan(pieceWeight('P'));
  expect(pieceWeight('r')).toBe(pieceWeight('R'));
  expect(pieceWeight(undefined)).toBe(1);
  expect(squarePan('a0')).toBeLessThan(0);
  expect(squarePan('i0')).toBeGreaterThan(0);
  expect(squarePan('e0')).toBeCloseTo(0);
  expect(squarePan(undefined)).toBe(0);
  const heavy = planCue('move', { piece: 'K', square: 'e0', step: 0 });
  const light = planCue('move', { piece: 'P', square: 'e0', step: 0 });
  const freq = (voices: AudioVoice[]) => voices.find((v) => v.kind === 'modal')!.freq;
  expect(freq(heavy)).toBeLessThan(freq(light));
});
