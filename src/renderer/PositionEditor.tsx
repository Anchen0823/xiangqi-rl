import { parseFenBoard } from './board-model';
import { EDITOR_PIECES, EMPTY_FEN, INITIAL_FEN, positionError } from './position-editor';
import type { Side } from '../shared/protocol';

export interface EditorDraft { fen: string; tool: string; source: string | null }

interface Props {
  draft: EditorDraft;
  busy: boolean;
  onChange: (draft: EditorDraft) => void;
  onApply: () => void;
  onCancel: () => void;
}

const labels = Object.fromEntries(parseFenBoard(INITIAL_FEN).map((piece) => [piece.code, piece.label]));

export function PositionEditor({ draft, busy, onChange, onApply, onCancel }: Props) {
  const error = positionError(draft.fen);
  const side: Side = draft.fen.split(' ')[1] === 'b' ? 'black' : 'red';
  return <section className="position-editor" aria-label="编辑局面">
    <h2>编辑局面 <small>摆出你想研究的棋局</small></h2>
    <p className="editor-help">选棋子后点击棋盘摆放；选择“移动”后，依次点击起点和终点。应用后从新局面开始，着法记录与计时归零。</p>
    <fieldset disabled={busy}>
      <legend>摆放棋子</legend>
      {['red', 'black'].map((color) => <div className="piece-palette" key={color} aria-label={`${color === 'red' ? '红方' : '黑方'}棋子`}>
        {EDITOR_PIECES.filter((code) => (code === code.toUpperCase()) === (color === 'red')).map((code) => <button key={code} className={`palette-piece ${color}`} aria-label={`摆放${color === 'red' ? '红' : '黑'}${labels[code]}`} aria-pressed={draft.tool === code} onClick={() => onChange({ ...draft, tool: code, source: null })}>{labels[code]}</button>)}
      </div>)}
      <div className="editor-tools">
        <button aria-pressed={draft.tool === 'move'} onClick={() => onChange({ ...draft, tool: 'move', source: null })}>移动棋子</button>
        <button aria-pressed={draft.tool === 'erase'} onClick={() => onChange({ ...draft, tool: 'erase', source: null })}>删除棋子</button>
      </div>
      <label>先行方<select value={side} onChange={(event) => onChange({ ...draft, fen: draft.fen.replace(/ [wb] /, ` ${event.target.value === 'red' ? 'w' : 'b'} `) })}><option value="red">红方先行</option><option value="black">黑方先行</option></select></label>
      <div className="editor-tools">
        <button onClick={() => onChange({ ...draft, fen: INITIAL_FEN.replace(' w ', side === 'red' ? ' w ' : ' b '), source: null })}>恢复初始</button>
        <button onClick={() => onChange({ ...draft, fen: EMPTY_FEN.replace(' w ', side === 'red' ? ' w ' : ' b '), source: null })}>清空棋盘</button>
      </div>
    </fieldset>
    <p className={`editor-validation ${error ? 'invalid' : ''}`} role="status">{busy ? '正在同步引擎…' : error ?? '布局检查通过，应用时将校验行棋合法性。'}</p>
    <div className="editor-actions"><button disabled={busy} onClick={onCancel}>取消编辑</button><button className="primary-action" disabled={busy || !!error} onClick={onApply}>应用局面</button></div>
  </section>;
}
