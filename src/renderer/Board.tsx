import { parseFenBoard, squarePosition } from './board-model';

interface Props {
  fen: string;
  legalMoves: string[];
  selected: string | null;
  lastMove?: string;
  flipped: boolean;
  disabled: boolean;
  onSquare: (square: string) => void;
}

export function Board({ fen, legalMoves, selected, lastMove, flipped, disabled, onSquare }: Props) {
  const pieces = parseFenBoard(fen);
  const destinations = new Set(legalMoves.filter((move) => move.startsWith(selected ?? '--')).map((move) => move.slice(2)));
  const lastSquares = new Set(lastMove ? [lastMove.slice(0, 2), lastMove.slice(2)] : []);
  return (
    <div className={`board-shell ${disabled ? 'disabled' : ''}`} aria-label="中国象棋棋盘">
      <svg className="board-grid" viewBox="0 0 800 900" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="board-wood" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#c98b4d" />
            <stop offset="0.52" stopColor="#bd7e43" />
            <stop offset="1" stopColor="#a96838" />
          </linearGradient>
          <linearGradient id="river-wood" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#c98b4f" />
            <stop offset="1" stopColor="#b9763e" />
          </linearGradient>
        </defs>
        <rect className="board-surface" width="800" height="900" />
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
        </g>
      </svg>
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
            onClick={() => onSquare(square)}
          />
        );
      })}
      {pieces.map((piece) => (
        <button
          type="button"
          key={piece.square}
          className={`piece ${piece.side} ${selected === piece.square ? 'selected' : ''}`}
          style={squarePosition(piece.square, flipped)}
          onClick={() => onSquare(piece.square)}
          aria-label={`${piece.side === 'red' ? '红' : '黑'}${piece.label} ${piece.square}`}
        >{piece.label}</button>
      ))}
    </div>
  );
}
