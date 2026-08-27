import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Analysis, Difficulty, PositionSnapshot, SavedGameV1, Side } from '../shared/protocol';
import { Board } from './Board';
import { parseFenBoard } from './board-model';

const INITIAL_FEN = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';
const difficulties: Array<{ value: Difficulty; label: string }> = [
  { value: 'beginner', label: '入门' }, { value: 'casual', label: '休闲' },
  { value: 'advanced', label: '进阶' }, { value: 'club', label: '棋社' },
  { value: 'expert', label: '高手' },
];
const resultLabels: Record<string, string> = {
  checkmate: '将死', stalemate: '困毙', natural_limit: '自然限着和棋',
  perpetual_check: '长将判负', perpetual_chase: '长捉判负',
  mutual_repetition: '双方循环和棋', early_repetition_red_must_deviate: '25回合内红方不变判负',
};

export function App() {
  const [snapshot, setSnapshot] = useState<PositionSnapshot | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [mode, setMode] = useState<'ai' | 'local'>('ai');
  const [humanSide, setHumanSide] = useState<Side>('red');
  const [difficulty, setDifficulty] = useState<Difficulty>('club');
  const [thinking, setThinking] = useState(false);
  const [analysisEnabled, setAnalysisEnabled] = useState(true);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [initialFen, setInitialFen] = useState(INITIAL_FEN);
  const [fenDraft, setFenDraft] = useState(INITIAL_FEN);
  const [clocksMs, setClocksMs] = useState({ red: 0, black: 0 });

  const run = useCallback(async <T,>(method: string, params: Record<string, unknown> = {}) => {
    try {
      setError(null);
      return await window.xiangqi.request<T>(method, params);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      throw cause;
    }
  }, []);

  useEffect(() => { void run<PositionSnapshot>('newGame').then(setSnapshot); }, [run]);

  useEffect(() => {
    if (!snapshot || snapshot.result.kind !== 'ongoing') return;
    const side = snapshot.sideToMove;
    let lastTick = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const elapsed = now - lastTick;
      lastTick = now;
      setClocksMs((current) => ({ ...current, [side]: current[side] + elapsed }));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [snapshot?.fen, snapshot?.result.kind, snapshot?.sideToMove]);

  useEffect(() => {
    if (!snapshot || !analysisEnabled || snapshot.result.kind !== 'ongoing') { setAnalysis(null); return; }
    let canceled = false;
    void run<Analysis>('analyze', { difficulty }).then((value) => { if (!canceled) setAnalysis(value); }).catch(() => undefined);
    return () => { canceled = true; };
  }, [snapshot?.fen, snapshot?.result.kind, analysisEnabled, difficulty, run]);

  useEffect(() => {
    if (!snapshot || mode !== 'ai' || snapshot.sideToMove === humanSide || snapshot.result.kind !== 'ongoing' || thinking) return;
    let canceled = false;
    setThinking(true);
    void run<Analysis>('analyze', { difficulty })
      .then(async (value) => {
        if (!value.pv[0] || canceled) return;
        await new Promise((resolve) => setTimeout(resolve, 300));
        if (!canceled) setSnapshot(await run<PositionSnapshot>('playMove', { move: value.pv[0] }));
      })
      .catch(() => undefined)
      .finally(() => { if (!canceled) setThinking(false); });
    return () => { canceled = true; };
  }, [snapshot?.fen, snapshot?.result.kind, snapshot?.sideToMove, mode, humanSide, difficulty, thinking, run]);

  const piecesBySquare = useMemo(() => {
    const entries = snapshot ? parseFenBoard(snapshot.fen).map((piece) => [piece.square, piece] as const) : [];
    return new Map(entries);
  }, [snapshot?.fen]);

  async function handleSquare(square: string) {
    if (!snapshot || thinking || snapshot.result.kind !== 'ongoing') return;
    if (mode === 'ai' && snapshot.sideToMove !== humanSide) return;
    const piece = piecesBySquare.get(square);
    if (!selected) {
      if (piece?.side === snapshot.sideToMove) setSelected(square);
      return;
    }
    if (piece?.side === snapshot.sideToMove) { setSelected(square); return; }
    const encoded = `${selected}${square}`;
    if (!snapshot.legalMoves.includes(encoded)) { setSelected(null); return; }
    setSelected(null);
    setSnapshot(await run<PositionSnapshot>('playMove', { move: encoded }));
  }

  async function newGame() {
    setSelected(null); setAnalysis(null); setInitialFen(INITIAL_FEN); setFenDraft(INITIAL_FEN);
    setClocksMs({ red: 0, black: 0 });
    setSnapshot(await run<PositionSnapshot>('newGame'));
  }

  async function undo() {
    if (!snapshot?.history.length || thinking) return;
    let next = await run<PositionSnapshot>('undo');
    if (mode === 'ai' && next.history.length && next.sideToMove !== humanSide) next = await run<PositionSnapshot>('undo');
    setSelected(null); setSnapshot(next);
  }

  async function loadFen() {
    const next = await run<PositionSnapshot>('loadFen', { fen: fenDraft.trim() });
    setInitialFen(fenDraft.trim()); setSelected(null); setSnapshot(next);
  }

  async function saveGame() {
    if (!snapshot) return;
    const game: SavedGameV1 = {
      schemaVersion: 1, initialFen, moves: snapshot.history.map((entry) => entry.move),
      clocksMs,
      settings: { mode, humanSide, difficulty }, savedAt: new Date().toISOString(),
    };
    await window.xiangqi.saveGame(game);
  }

  async function openGame() {
    const opened = await window.xiangqi.openGame();
    if (opened.canceled || !opened.game) return;
    const game = opened.game;
    let next = await run<PositionSnapshot>('loadFen', { fen: game.initialFen });
    for (const move of game.moves) next = await run<PositionSnapshot>('playMove', { move });
    setMode(game.settings.mode); setHumanSide(game.settings.humanSide); setDifficulty(game.settings.difficulty);
    setClocksMs(game.clocksMs ?? { red: 0, black: 0 });
    setInitialFen(game.initialFen); setFenDraft(next.fen); setSelected(null); setSnapshot(next);
  }

  const status = snapshot?.result.kind !== 'ongoing'
    ? `${snapshot?.result.kind === 'draw' ? '和棋' : snapshot?.result.kind === 'red_win' ? '红方胜' : '黑方胜'} · ${resultLabels[snapshot?.result.reason ?? ''] ?? snapshot?.result.reason}`
    : thinking ? 'AI 正在思考…' : `${snapshot?.sideToMove === 'red' ? '红方' : '黑方'}行棋`;
  const clock = (milliseconds: number) => {
    const seconds = Math.floor(milliseconds / 1000);
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><span className="seal">弈</span><h1>弈境</h1><p>XIANGQI RL</p></div>
        <nav>
          <button onClick={() => void newGame()}>新局</button>
          <button onClick={() => void openGame()}>载入</button>
          <button onClick={() => void saveGame()} disabled={!snapshot}>保存</button>
        </nav>
      </header>

      <section className="workspace">
        <aside className="left-panel panel">
          <h2>对局设置</h2>
          <label>模式<select value={mode} onChange={(event) => setMode(event.target.value as 'ai' | 'local')}><option value="ai">人机对弈</option><option value="local">本地双人</option></select></label>
          <label>执子<select value={humanSide} disabled={mode === 'local'} onChange={(event) => setHumanSide(event.target.value as Side)}><option value="red">红方</option><option value="black">黑方</option></select></label>
          <label>棋力<select value={difficulty} disabled={mode === 'local'} onChange={(event) => setDifficulty(event.target.value as Difficulty)}>{difficulties.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <div className="action-row"><button onClick={() => void undo()} disabled={!snapshot?.history.length || thinking}>悔棋</button><button onClick={() => setFlipped((value) => !value)}>翻转</button></div>
          <label className="switch"><input type="checkbox" checked={analysisEnabled} onChange={(event) => setAnalysisEnabled(event.target.checked)} />显示局面分析</label>
          <div className="rule-counter"><span>自然限着</span><strong>{snapshot?.noCapturePlies ?? 0}<small>/120 着</small></strong></div>
          <details><summary>导入 FEN</summary><textarea value={fenDraft} onChange={(event) => setFenDraft(event.target.value)} /><button onClick={() => void loadFen()}>载入局面</button></details>
        </aside>

        <section className="game-stage">
          <div className="status"><time>红 {clock(clocksMs.red)}</time><span className={snapshot?.sideToMove ?? 'red'} />{status}<time>黑 {clock(clocksMs.black)}</time></div>
          {snapshot ? <Board fen={snapshot.fen} legalMoves={snapshot.legalMoves} selected={selected} lastMove={snapshot.history.at(-1)?.move} flipped={flipped} disabled={thinking} onSquare={(square) => void handleSquare(square)} /> : <div className="loading">正在启动原生规则引擎…</div>}
          {error && <div className="error-banner">{error}</div>}
        </section>

        <aside className="right-panel panel">
          <h2>棋局分析</h2>
          <div className="evaluation"><span>红方优势</span><strong>{analysis ? `${analysis.scoreCp >= 0 ? '+' : ''}${(analysis.scoreCp / 100).toFixed(2)}` : '—'}</strong></div>
          <div className="pv"><span>推荐着法</span><strong>{analysis?.pv[0]?.toUpperCase() ?? '等待行棋'}</strong><small>深度 {analysis?.depth ?? 0} · {analysis?.nodes ?? 0} 节点</small></div>
          <h3>着法记录</h3>
          <ol className="moves">{snapshot?.history.map((entry, index) => <li key={`${entry.move}-${index}`}><span>{index + 1}</span>{entry.move.toUpperCase()}{entry.check ? <b>将</b> : null}</li>)}</ol>
          {!snapshot?.history.length && <p className="empty">棋局尚未开始</p>}
        </aside>
      </section>
    </main>
  );
}
