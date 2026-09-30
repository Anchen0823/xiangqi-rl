import type { Cue } from './game-feedback';
import { planCue, type AudioVoice, type CueContext } from './audio-voices';

// Locally synthesized wood knocks and bronze-like tones: no network or audio
// assets. Sound design lives in audio-voices.ts; this class only schedules it.
export class GameAudio {
  private context?: AudioContext;
  private master?: GainNode;
  private space?: DelayNode;
  private noiseBuffer?: AudioBuffer;
  private volume = 0.45;
  private enabled = true;
  private generation = 0;
  private step = 0;

  configure(enabled: boolean, volume: number) {
    this.enabled = enabled;
    this.volume = Math.max(0, Math.min(1, volume));
    if (!enabled) this.generation++;
    if (this.context && this.master) this.master.gain.setTargetAtTime(enabled ? this.volume * 0.35 : 0, this.context.currentTime, 0.015);
  }

  async unlock() {
    if (!this.enabled) return;
    try {
      if (!this.context) {
        this.context = new AudioContext();
        this.master = this.context.createGain();
        this.master.gain.value = this.volume * 0.35;
        // A short feedback delay stands in for room reverb so the check and
        // result bells decay in a space instead of ending abruptly.
        this.space = this.context.createDelay(0.5);
        this.space.delayTime.value = 0.13;
        const feedback = this.context.createGain();
        feedback.gain.value = 0.32;
        const wet = this.context.createGain();
        wet.gain.value = 0.5;
        this.space.connect(feedback);
        feedback.connect(this.space);
        this.space.connect(wet);
        wet.connect(this.master);
        this.master.connect(this.context.destination);
      }
      if (this.context.state === 'suspended') await this.context.resume();
    } catch { /* Audio availability must never interrupt a legal move. */ }
  }

  /** Fire and forget: sound must never block or fail a move. */
  play(cue: Cue, context?: CueContext) {
    if (!this.enabled || !this.volume) return;
    const generation = this.generation;
    void this.unlock().then(() => {
      const ctx = this.context, master = this.master, space = this.space;
      if (!ctx || !master || ctx.state !== 'running' || !this.enabled || generation !== this.generation) return;
      try {
        for (const voice of planCue(cue, { step: this.step++, ...context })) this.render(voice, ctx, master, space);
      } catch { /* A dropped sound is preferable to a dropped move. */ }
    });
  }

  private render(voice: AudioVoice, ctx: AudioContext, master: GainNode, space?: DelayNode) {
    const start = ctx.currentTime + voice.delay;
    const nodes: AudioNode[] = [];
    const panner = ctx.createStereoPanner();
    panner.pan.value = voice.pan;
    const envelope = ctx.createGain();
    const peak = Math.max(0.0002, voice.gain);
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.linearRampToValueAtTime(peak, start + voice.attack);
    envelope.gain.exponentialRampToValueAtTime(0.0001, start + voice.attack + voice.decay);
    panner.connect(envelope);
    envelope.connect(master);
    nodes.push(panner, envelope);
    if (space && voice.space > 0) {
      const send = ctx.createGain();
      send.gain.value = voice.space;
      envelope.connect(send);
      send.connect(space);
      // The send feeds a long-lived bus, so it must be torn down with the voice.
      nodes.push(send);
    }
    const sources: AudioScheduledSourceNode[] = [];
    const stop = start + voice.attack + voice.decay + 0.03;

    if (voice.kind === 'noise') {
      const source = ctx.createBufferSource();
      source.buffer = this.noise(ctx);
      const band = ctx.createBiquadFilter();
      band.type = 'bandpass';
      band.frequency.value = Math.max(40, voice.colour ?? 2000);
      band.Q.value = 1.1;
      source.connect(band);
      band.connect(panner);
      nodes.push(band);
      sources.push(source);
    } else if (voice.kind === 'thump') {
      const oscillator = ctx.createOscillator();
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(voice.freq * 1.6, start);
      oscillator.frequency.exponentialRampToValueAtTime(Math.max(30, voice.freq * 0.55), start + voice.decay);
      oscillator.connect(panner);
      nodes.push(oscillator);
      sources.push(oscillator);
    } else {
      const weights = voice.kind === 'bell' ? [1, 0.5, 0.32, 0.2, 0.12, 0.08] : [1, 0.55, 0.32, 0.18];
      voice.partials?.forEach((ratio, index) => {
        const oscillator = ctx.createOscillator();
        oscillator.type = voice.kind === 'bell' ? 'sine' : 'triangle';
        oscillator.frequency.setValueAtTime(voice.freq * ratio * (1 + (index % 2 ? 0.004 : -0.004)), start);
        const partial = ctx.createGain();
        partial.gain.value = weights[index] ?? 0.06;
        oscillator.connect(partial);
        partial.connect(panner);
        nodes.push(partial);
        sources.push(oscillator);
      });
    }

    for (const source of sources) { source.start(start); source.stop(stop); }
    const first = sources[0];
    if (first) {
      first.onended = () => { for (const node of nodes) node.disconnect(); };
    } else {
      setTimeout(() => { for (const node of nodes) node.disconnect(); }, (stop - ctx.currentTime + 0.1) * 1000);
    }
  }

  private noise(ctx: AudioContext): AudioBuffer {
    if (!this.noiseBuffer || this.noiseBuffer.sampleRate !== ctx.sampleRate) {
      const buffer = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 0.5), ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let index = 0; index < data.length; index += 1) data[index] = Math.random() * 2 - 1;
      this.noiseBuffer = buffer;
    }
    return this.noiseBuffer;
  }

  dispose() {
    this.generation++;
    const context = this.context;
    this.context = undefined;
    this.master = undefined;
    this.space = undefined;
    this.noiseBuffer = undefined;
    void context?.close();
  }
}
