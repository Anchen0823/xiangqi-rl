import { parseFenBoard, squarePosition } from './board-model';
import type { Side } from '../shared/protocol';
import type { MoveFeedback } from './game-feedback';

interface Props {
  fen: string;
  legalMoves: string[];
  selected: string | null;
  lastMove?: string;
  flipped: boolean;
  disabled: boolean;
  feedback?: (MoveFeedback & { id: number }) | null;
  checkedSide?: Side;
  onSquare: (square: string) => void;
}

export function Board({ fen, legalMoves, selected, lastMove, flipped, disabled, feedback, checkedSide, onSquare }: Props) {
  const pieces = parseFenBoard(fen);
  const destinations = new Set(legalMoves.filter((move) => move.startsWith(selected ?? '--')).map((move) => move.slice(2)));
  const lastSquares = new Set(lastMove ? [lastMove.slice(0, 2), lastMove.slice(2)] : []);
  return (
    <div className={`board-shell ${disabled ? 'disabled' : ''}`} aria-label="中国象棋棋盘">
      <svg className="board-grid" viewBox="0 0 800 900" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="board-wood" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#f1d4a0" />
            <stop offset="0.52" stopColor="#e7c18b" />
            <stop offset="1" stopColor="#d6a76d" />
          </linearGradient>
          <linearGradient id="river-wood" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#e9c795" />
            <stop offset="1" stopColor="#e8c28d" />
          </linearGradient>
          <filter id="wood-grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency=".035 .004" numOctaves="2" seed="12" />
            <feColorMatrix type="saturate" values="0" />
          </filter>
        </defs>
        <rect className="board-surface" width="800" height="900" />
        <rect className="wood-texture" width="800" height="900" filter="url(#wood-grain)" opacity=".09" />
        <rect className="river-surface" y="400" width="800" height="100" />
        <g className="board-lines">
          {Array.from({ length: 10 }, (_, rank) => (
            <line key={`rank-${rank}`} x1="0" y1={rank * 100} x2="800" y2={rank * 100} />
          ))}
          <line x1="0" y1="0" x2="0" y2="900" />
          <line x1="800" y1="0" x2="800" y2="900" />
          {Array.from({ length: 7 }, (_, index) => {
            const file = (index + 1) * 100;
            return (
              <g key={`file-${file}`}>
                <line x1={file} y1="0" x2={file} y2="400" />
                <line x1={file} y1="500" x2={file} y2="900" />
              </g>
            );
          })}
          <path d="M300 0 L500 200 M500 0 L300 200" />
          <path d="M300 700 L500 900 M500 700 L300 900" />
          {[...[1, 7].flatMap((x) => [2, 7].map((y) => [x, y])), ...[0, 2, 4, 6, 8].flatMap((x) => [3, 6].map((y) => [x, y]))].map(([x, y]) => <g key={`mark-${x}-${y}`} strokeWidth="1.4">{[-1, 1].flatMap((dx) => [-1, 1].map((dy) => (x + dx >= 0 && x + dx <= 8) ? <path key={`${dx}-${dy}`} d={`M${x * 100 + dx * 20} ${y * 100 + dy * 7} H${x * 100 + dx * 7} V${y * 100 + dy * 20}`} /> : null))}</g>)}
        </g>
      </svg>
      <div className="board-grain" aria-hidden="true" />
      <div className="file-labels" aria-hidden="true">{(flipped ? ['1', '2', '3', '4', '5', '6', '7', '8', '9'] : ['九', '八', '七', '六', '五', '四', '三', '二', '一']).map((label) => <span key={label}>{label}</span>)}</div>
      <div className="river"><span>楚 河</span><span>漢 界</span></div>
      {Array.from({ length: 90 }, (_, index) => {
        const file = index % 9;
        const rank = Math.floor(index / 9);
        const square = `${String.fromCharCode(97 + file)}${rank}`;
        const position = squarePosition(square, flipped);
        return (
          <button
            type="button"
            key={square}
            className={`square-hit ${destinations.has(square) ? 'destination' : ''} ${lastSquares.has(square) ? 'last' : ''}`}
            style={position}
            aria-label={square}
            disabled={disabled || pieces.some((piece) => piece.square === square)}
            onClick={() => onSquare(square)}
          />
        );
      })}
      {pieces.map((piece) => (
        <button
          type="button"
          key={piece.square}
          className={`piece ${piece.side} ${selected === piece.square ? 'selected' : ''} ${feedback?.square === piece.square ? 'just-landed' : ''} ${piece.code.toLowerCase() === 'k' && piece.side === checkedSide ? 'in-check' : ''}`}
          style={squarePosition(piece.square, flipped)}
          onClick={() => onSquare(piece.square)}
          aria-label={`${piece.side === 'red' ? '红' : '黑'}${piece.label} ${piece.square}`}
          disabled={disabled}
        >{piece.label}</button>
      ))}
      {feedback && <div key={feedback.id} className={`impact ${feedback.capture ? 'capture-impact' : ''}`} style={squarePosition(feedback.square, flipped)} aria-hidden="true"><i /><i /><i /></div>}
    </div>
  );
}
