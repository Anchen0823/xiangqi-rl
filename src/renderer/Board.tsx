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
      <div className="board-grid" />
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
