import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Analysis, Difficulty, PositionSnapshot, SavedGameV1, Side } from '../shared/protocol';
import { Board } from './Board';
import { parseFenBoard } from './board-model';
import { recommendedMove, chineseMoves } from './notation';
import { GameAudio } from './game-audio';
import { cueTitles, moveFeedback, type Cue, type MoveFeedback } from './game-feedback';
import { PositionEditor, type EditorDraft } from './PositionEditor';
import { editSquare, INITIAL_FEN, positionError } from './position-editor';

function savedAudio() {
  try {
    const value = JSON.parse(localStorage.getItem('xiangqi-audio') ?? '{}');
    return { enabled: value.enabled !== false, volume: typeof value.volume === 'number' && Number.isFinite(value.volume) ? Math.max(0, Math.min(1, value.volume)) : 0.45 };
  } catch { return { enabled: true, volume: 0.45 }; }
}

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
  const [desktopModel,setDesktopModel]=useState('基础搜索');
  useEffect(()=>{void window.desktopModels?.list().then(models=>{const model=models.find(m=>m.mode==='standard');setDesktopModel(model?.status==='available'?model.name:model?.note??'模型空位 · 基础搜索');}).catch(()=>setDesktopModel('模型状态不可用'));},[]);
  const [snapshot, setSnapshot] = useState<PositionSnapshot | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [mode, setMode] = useState<'ai' | 'local'>('ai');
  const [humanSide, setHumanSide] = useState<Side>('red');
  const [difficulty, setDifficulty] = useState<Difficulty>('club');
  const [analysisEnabled, setAnalysisEnabled] = useState(true);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  // Which position the analysis above describes/awaits. Kept as state, not a
  // ref, so the "分析中…" placeholder renders on the very first paint.
  const [analysisFen, setAnalysisFen] = useState('');
  const [stopNonce, setStopNonce] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [initialFen, setInitialFen] = useState(INITIAL_FEN);
  const [fenDraft, setFenDraft] = useState(INITIAL_FEN);
  const [clocksMs, setClocksMs] = useState({ red: 0, black: 0 });
  const [audio] = useState(() => new GameAudio());
  const [audioSettings, setAudioSettings] = useState(savedAudio);
  const [feedback, setFeedback] = useState<(MoveFeedback & { id: number }) | null>(null);
  const [resultVisible, setResultVisible] = useState(true);
  const [editor, setEditor] = useState<EditorDraft | null>(null);
  const [editorBusy, setEditorBusy] = useState(false);
  const editing = useRef(false);
  const moveInFlight = useRef<Promise<unknown> | null>(null);
  useEffect(() => {
    audio.configure(audioSettings.enabled, audioSettings.volume);
    try { localStorage.setItem('xiangqi-audio', JSON.stringify(audioSettings)); } catch { /* Private storage may be unavailable. */ }
  }, [audio, audioSettings]);
  useEffect(() => () => audio.dispose(), [audio]);
  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(null), 1500);
    return () => window.clearTimeout(timer);
  }, [feedback]);
  const commitMove = useCallback((before: PositionSnapshot, after: PositionSnapshot) => {
    const next = moveFeedback(before, after);
    setSnapshot(after);
    setResultVisible(true);
    if (next) {
      setFeedback({ ...next, id: performance.now() });
      const landed = parseFenBoard(after.fen).find((piece) => piece.square === next.square);
      void audio.play(next.cue, { piece: landed?.code, square: next.square, step: after.history.length });
    }
  }, [audio]);
  // Remembers which position an "analyze" request was already issued for, so a
  // reaction to an unrelated state change cannot buy a second search.
  const analyzedFen = useRef<string | null>(null);
  const historyNotation = useMemo(() => chineseMoves(initialFen, snapshot?.history.map((entry) => entry.move) ?? []), [initialFen, snapshot?.history]);

  const run = useCallback(async <T,>(method: string, params: Record<string, unknown> = {}) => {
    try {
      setError(null);
      return await window.xiangqi.request<T>(method, params);
    } catch (cause) {
      const raw = cause instanceof Error ? cause.message : String(cause);
      const message = raw.includes('FEN leaves the side that just moved in check')
        ? '局面无效：非行棋方正被将军，请调整棋子或更换先行方。'
        : raw.includes('FEN must contain both kings') ? '局面必须包含红帅与黑将。' : raw;
      setError(message);
      throw cause;
    }
  }, []);

  // The engine handles one request at a time, so a queued playMove waits for the
  // in-flight analysis to finish. Sending `stop` first lets that search return
  // immediately instead of holding the move for the whole search budget.
  const stopAnalysis = useCallback(async () => {
    try { await window.xiangqi.request('stop'); } catch { /* Best effort: nothing is running. */ }
  }, []);

  useEffect(() => { void run<PositionSnapshot>('newGame').then(setSnapshot); }, [run]);

  useEffect(() => {
    if (!snapshot || snapshot.result.kind !== 'ongoing' || editor) return;
    const side = snapshot.sideToMove;
    let lastTick = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const elapsed = now - lastTick;
      lastTick = now;
      setClocksMs((current) => ({ ...current, [side]: current[side] + elapsed }));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [snapshot?.fen, snapshot?.result.kind, snapshot?.sideToMove, !!editor]);

  // One search per position serves both the analysis panel and the AI's choice
  // of reply. The engine is strictly serial, so a second concurrent analyze
  // would only queue behind this one and double the wait.
  useEffect(() => {
    if (!snapshot || snapshot.result.kind !== 'ongoing' || !analysisEnabled || editor) {
      setAnalysis(null); setAnalysisFen(''); analyzedFen.current = null; return;
    }
    if (analyzedFen.current === snapshot.fen) return;
    analyzedFen.current = snapshot.fen;
    const fen = snapshot.fen;
    let canceled = false;
    setAnalysis(null);
    setAnalysisFen(fen);
    void run<Analysis>('analyze', { difficulty })
      .then((value) => { if (!canceled) setAnalysis(value); })
      .catch(() => { if (!canceled) { setAnalysis(null); setAnalysisFen(''); } });
    return () => { canceled = true; analyzedFen.current = null; };
  }, [snapshot, analysisEnabled, difficulty, run, stopNonce, !!editor]);

  // The AI plays the principal variation of that same analysis, so one search
  // per position covers both the panel and the reply.
  const playedForFen = useRef<string | null>(null);
  useEffect(() => {
    if (!snapshot || editor || mode !== 'ai' || snapshot.sideToMove === humanSide) return;
    if (analysisFen !== snapshot.fen || !analysis?.pv[0]) return;
    if (playedForFen.current === snapshot.fen) return;
    playedForFen.current = snapshot.fen;
    const move = analysis.pv[0];
    let canceled = false;
    const timer = window.setTimeout(() => {
      if (canceled || editing.current) return;
      const request = run<PositionSnapshot>('playMove', { move }).then((next) => { if (!canceled) commitMove(snapshot, next); }).catch(() => undefined);
      moveInFlight.current = request;
      void request.finally(() => { if (moveInFlight.current === request) moveInFlight.current = null; });
    }, 300);
    return () => { canceled = true; window.clearTimeout(timer); playedForFen.current = null; };
  }, [snapshot, analysis, analysisFen, mode, humanSide, difficulty, run, commitMove, !!editor]);

  const pending = useMemo(
    () => Boolean(!editor && snapshot && snapshot.result.kind === 'ongoing' && mode === 'ai' && snapshot.sideToMove !== humanSide),
    [snapshot, mode, humanSide, !!editor],
  );
  // The shown score belongs to the current position only; anything else is a
  // guess in flight, and while the AI thinks its search is the panel's answer.
  const shownAnalysis = !editor && snapshot && analysisFen === snapshot.fen ? analysis : null;
  const recommended = recommendedMove(snapshot, analysisFen, shownAnalysis);

  const piecesBySquare = useMemo(() => {
    const entries = snapshot ? parseFenBoard(snapshot.fen).map((piece) => [piece.square, piece] as const) : [];
    return new Map(entries);
  }, [snapshot?.fen]);

  async function handleSquare(square: string) {
    if (editor) {
      if (editorBusy) return;
      setError(null);
      if (editor.tool === 'move') {
        const piece = parseFenBoard(editor.fen).find((item) => item.square === square);
        if (!editor.source) { if (piece) setEditor({ ...editor, source: square }); return; }
        if (editor.source === square) { setEditor({ ...editor, source: null }); return; }
        const source = parseFenBoard(editor.fen).find((item) => item.square === editor.source);
        if (source) setEditor({ ...editor, fen: editSquare(editor.fen, square, source.code, editor.source), source: null });
      } else setEditor({ ...editor, fen: editSquare(editor.fen, square, editor.tool === 'erase' ? null : editor.tool), source: null });
      return;
    }
    if (editing.current || moveInFlight.current) return;
    if (!snapshot || pending || snapshot.result.kind !== 'ongoing') return;
    if (mode === 'ai' && snapshot.sideToMove !== humanSide) return;
    const piece = piecesBySquare.get(square);
    if (!selected) {
      if (piece?.side === snapshot.sideToMove) {
        setSelected(square);
        void audio.play('select', { piece: piece.code, square, step: snapshot.history.length });
      }
      return;
    }
    if (piece?.side === snapshot.sideToMove) {
      setSelected(square);
      void audio.play('select', { piece: piece.code, square, step: snapshot.history.length });
      return;
    }
    const encoded = `${selected}${square}`;
    if (!snapshot.legalMoves.includes(encoded)) { setSelected(null); return; }
    setSelected(null);
    // Cut the speculative analysis short so this move is not queued behind it,
    // and re-arm the analysis for the resulting position.
    void stopAnalysis();
    setStopNonce((value) => value + 1);
    const request = run<PositionSnapshot>('playMove', { move: encoded });
    moveInFlight.current = request;
    try { commitMove(snapshot, await request); }
    catch { /* run displays the engine error. */ }
    finally { if (moveInFlight.current === request) moveInFlight.current = null; }
  }

  async function startEditing() {
    if (!snapshot || editing.current) return;
    editing.current = true;
    setEditor({ fen: snapshot.fen, tool: 'move', source: null });
    setEditorBusy(true); setSelected(null); setFeedback(null); setError(null);
    try {
      await stopAnalysis();
      await moveInFlight.current;
      const current = await run<PositionSnapshot>('snapshot');
      setSnapshot(current);
      setEditor({ fen: current.fen, tool: 'move', source: null });
    } catch { editing.current = false; setEditor(null); }
    finally { setEditorBusy(false); }
  }

  function cancelEditing() {
    editing.current = false; setEditor(null); setSelected(null); setError(null);
  }

  async function applyPosition() {
    if (!editor || editorBusy) return;
    const invalid = positionError(editor.fen);
    if (invalid) { setError(invalid); return; }
    setEditorBusy(true);
    try {
      const next = await run<PositionSnapshot>('loadFen', { fen: editor.fen });
      setInitialFen(next.fen); setFenDraft(next.fen); setSnapshot(next);
      setClocksMs({ red: 0, black: 0 }); setResultVisible(true); setFeedback(null);
      cancelEditing();
    } catch { /* Keep the draft for correction; native loadFen preserves the old position. */ }
    finally { setEditorBusy(false); }
  }

  async function newGame() {
    setFeedback(null); setResultVisible(true);
    setSelected(null); setAnalysis(null); setAnalysisFen(''); setInitialFen(INITIAL_FEN); setFenDraft(INITIAL_FEN);
    setClocksMs({ red: 0, black: 0 });
    setSnapshot(await run<PositionSnapshot>('newGame'));
  }

  async function undo() {
    if (!snapshot?.history.length || pending) return;
    void stopAnalysis();
    setStopNonce((value) => value + 1);
    let next = await run<PositionSnapshot>('undo');
    if (mode === 'ai' && next.history.length && next.sideToMove !== humanSide) next = await run<PositionSnapshot>('undo');
    setFeedback(null); setResultVisible(true); setSelected(null); setSnapshot(next);
  }

  async function loadFen() {
    await stopAnalysis();
    try {
      const next = await run<PositionSnapshot>('loadFen', { fen: fenDraft.trim() });
      setFeedback(null); setResultVisible(true); setInitialFen(next.fen); setSelected(null); setSnapshot(next);
      setClocksMs({ red: 0, black: 0 });
    } catch { /* run displays the engine error. */ }
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
    setFeedback(null); setResultVisible(true);
    let next = await run<PositionSnapshot>('loadFen', { fen: game.initialFen });
    for (const move of game.moves) next = await run<PositionSnapshot>('playMove', { move });
    setMode(game.settings.mode); setHumanSide(game.settings.humanSide); setDifficulty(game.settings.difficulty);
    setClocksMs(game.clocksMs ?? { red: 0, black: 0 });
    setInitialFen(game.initialFen); setFenDraft(next.fen); setSelected(null); setSnapshot(next);
  }

  const status = snapshot?.result.kind !== 'ongoing'
    ? `${snapshot?.result.kind === 'draw' ? '和棋' : snapshot?.result.kind === 'red_win' ? '红方胜' : '黑方胜'} · ${resultLabels[snapshot?.result.reason ?? ''] ?? snapshot?.result.reason}`
    : pending ? 'AI 正在思考…' : `${snapshot?.sideToMove === 'red' ? '红方' : '黑方'}行棋`;
  const clock = (milliseconds: number) => {
    const seconds = Math.floor(milliseconds / 1000);
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };
  const awaitingAnalysis = Boolean(!editor && snapshot && analysisEnabled && snapshot.result.kind === 'ongoing' && !pending && !shownAnalysis);
  const playerCard = (side: Side) => <div className={`player-card ${side}`}>
    <span className="player-avatar" aria-hidden="true">{side === 'red' ? '帅' : '将'}</span>
    <div><strong>{mode === 'ai' && side !== humanSide ? '弈境 AI' : mode === 'ai' ? '我方' : side === 'red' ? '红方棋手' : '黑方棋手'}</strong><small>{side === 'red' ? '红方' : '黑方'} · {mode === 'ai' && side !== humanSide ? difficulties.find((item) => item.value === difficulty)?.label : '执子对弈'}</small></div>
    <time>{clock(clocksMs[side])}</time>
    <span className={`turn-badge ${!editor && snapshot?.sideToMove === side && snapshot.result.kind === 'ongoing' ? 'active' : ''}`}>{editor ? '摆棋' : snapshot?.sideToMove === side && snapshot.result.kind === 'ongoing' ? '行棋中' : '候场'}</span>
  </div>;

  return (
    <main className="app-shell" onPointerDownCapture={() => void audio.unlock()} onKeyDownCapture={() => void audio.unlock()}>
      <header className="topbar">
        <div><span className="seal">弈</span><h1>弈境</h1><p>XIANGQI RL</p></div>
        <nav>
          <button onClick={() => void newGame()} disabled={!!editor}>新局</button>
          <button onClick={() => void openGame()} disabled={!!editor}>载入</button>
          <button onClick={() => void saveGame()} disabled={!snapshot || !!editor}>保存</button>
        </nav>
      </header>

      <section className="workspace">
        <aside className="left-panel panel">
          <p className="desktop-model-status" data-testid="standard-model">当前 AI：{desktopModel}</p>
          {editor ? <PositionEditor draft={editor} busy={editorBusy} onChange={(draft) => { setEditor(draft); setError(null); }} onApply={() => void applyPosition()} onCancel={cancelEditing} /> : <>
          <h2>对局设置</h2>
          <label>模式<select value={mode} onChange={(event) => setMode(event.target.value as 'ai' | 'local')}><option value="ai">人机对弈</option><option value="local">本地双人</option></select></label>
          <label>执子<select value={humanSide} disabled={mode === 'local'} onChange={(event) => setHumanSide(event.target.value as Side)}><option value="red">红方</option><option value="black">黑方</option></select></label>
          <label>棋力<select value={difficulty} disabled={mode === 'local'} onChange={(event) => setDifficulty(event.target.value as Difficulty)}>{difficulties.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label className="switch"><input type="checkbox" checked={analysisEnabled} onChange={(event) => setAnalysisEnabled(event.target.checked)} />显示局面分析</label>
          <div className="sound-control">
            <label className="switch"><input type="checkbox" checked={audioSettings.enabled} onChange={(event) => setAudioSettings((value) => ({ ...value, enabled: event.target.checked }))} />对局音效</label>
            <label className="volume-control">音量 <input aria-label="音效音量" type="range" min="0" max="100" value={Math.round(audioSettings.volume * 100)} disabled={!audioSettings.enabled} onChange={(event) => setAudioSettings((value) => ({ ...value, volume: Number(event.target.value) / 100 }))} /></label>
            <button className="sound-preview" disabled={!audioSettings.enabled} onClick={() => {
              const cycle: Cue[] = ['move', 'capture', 'check', 'checkmate', 'draw'];
              cycle.forEach((cue, index) => {
                window.setTimeout(() => void audio.play(cue, { step: index }), index * 620);
              });
            }}>试听</button>
          </div>
          <div className="rule-counter"><span>自然限着</span><strong>{snapshot?.noCapturePlies ?? 0}<small>/120 着</small></strong></div>
          <details><summary>导入 FEN</summary><textarea value={fenDraft} onChange={(event) => setFenDraft(event.target.value)} /><button onClick={() => void loadFen()}>载入局面</button></details>
          </>}
        </aside>

        <section className="game-stage">
          {playerCard(flipped ? 'red' : 'black')}
          <div className="status" role="status"><span className={snapshot?.sideToMove ?? 'red'} />{editor ? '编辑模式 · 对弈与分析已暂停' : snapshot ? status : '正在准备棋局'}</div>
          {snapshot ? <Board fen={editor?.fen ?? snapshot.fen} legalMoves={editor ? [] : snapshot.legalMoves} selected={editor ? editor.source : selected} lastMove={editor ? undefined : snapshot.history.at(-1)?.move} flipped={flipped} disabled={editor ? editorBusy : pending || snapshot.result.kind !== 'ongoing'} feedback={editor ? null : feedback} checkedSide={!editor && snapshot.result.kind === 'ongoing' && snapshot.history.at(-1)?.check ? snapshot.sideToMove : undefined} onSquare={(square) => void handleSquare(square)} /> : <div className="loading">正在启动原生规则引擎…</div>}
          {playerCard(flipped ? 'black' : 'red')}
          <nav className="board-toolbar" aria-label="棋盘工具">
            <button onClick={() => void undo()} disabled={!!editor || !snapshot?.history.length || pending}><span aria-hidden="true">↶</span>悔棋</button>
            <button onClick={() => setFlipped((value) => !value)} aria-pressed={flipped}><span aria-hidden="true">⇅</span>翻转棋盘</button>
            <button onClick={() => void startEditing()} disabled={!snapshot || !!editor} aria-pressed={!!editor}><span aria-hidden="true">✎</span>编辑局面</button>
          </nav>
          {!editor && feedback && ['capture', 'check'].includes(feedback.cue) && <div key={feedback.id} className={`event-callout ${feedback.cue}`} role="status"><span>{feedback.cue === 'check' ? '锋芒已至 · 应将' : '落子有声 · 得子'}</span><strong>{cueTitles[feedback.cue]}</strong></div>}
          {!editor && snapshot && snapshot.result.kind !== 'ongoing' && resultVisible && <section className={`result-card ${snapshot.result.kind}`} aria-label="对局结果" aria-live="polite">
            <div className="result-ornament" aria-hidden="true">弈</div>
            <span className="result-eyebrow">{snapshot.result.kind === 'draw' ? '一局终了 · 棋逢对手' : '一局终了 · 胜负已分'}</span>
            <h2>{snapshot.result.reason === 'checkmate' ? '绝杀' : snapshot.result.reason === 'stalemate' ? '困毙' : snapshot.result.kind === 'draw' ? '和棋' : '胜负已定'}</h2>
            <p className="result-winner">{snapshot.result.kind === 'draw' ? '双方握手言和' : snapshot.result.kind === 'red_win' ? '红方胜' : '黑方胜'}</p>
            <p>{snapshot.result.reason === 'checkmate' ? '将帅受攻，无解可应。' : snapshot.result.reason === 'stalemate' ? '未被将军，但已无合法着法，困毙判负。' : resultLabels[snapshot.result.reason] ?? snapshot.result.reason}</p>
            <div className="result-actions"><button onClick={() => setResultVisible(false)}>留局复盘</button><button onClick={() => void newGame()}>再弈一局</button></div>
          </section>}
          {error && <div className="error-banner">{error}</div>}
        </section>

        <aside className="right-panel panel">
          <h2>棋局分析</h2>
          <div className="evaluation"><span>红方优势</span><strong>{shownAnalysis ? `${shownAnalysis.scoreCp >= 0 ? '+' : ''}${(shownAnalysis.scoreCp / 100).toFixed(2)}` : '—'}</strong></div>
          <div className="pv">
            <span>推荐着法</span>
            <strong>{editor ? '编辑中 · 已暂停' : pending ? 'AI 正在思考…' : recommended ?? (awaitingAnalysis ? '分析中…' : '等待行棋')}</strong>
            <small>{pending ? '正在搜索最佳应着' : awaitingAnalysis ? '正在计算局面评分' : `深度 ${shownAnalysis?.depth ?? 0} · ${shownAnalysis?.nodes ?? 0} 节点`}</small>
          </div>
          <h3>着法记录</h3>
          <ol className="moves">{snapshot?.history.map((entry, index) => <li key={`${entry.move}-${index}`} title={entry.move}><span>{index + 1}</span>{historyNotation[index]}{entry.check ? <b>将</b> : null}</li>)}</ol>
          {!snapshot?.history.length && <p className="empty">棋局尚未开始</p>}
        </aside>
      </section>
    </main>
  );
}
