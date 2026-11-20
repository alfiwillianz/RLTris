import type { ReplaySnapshot } from "../types";
import { BOARD_WIDTH, PIECE_COLORS, VISIBLE_ROWS, boardOccupied, pieceCells } from "../lib/tetris";

interface BoardProps {
  snapshot: ReplaySnapshot | null;
  label: string;
  subtitle?: string;
}

const CELL = 20;

export default function Board({ snapshot, label, subtitle }: BoardProps) {
  const rows = snapshot?.rows ?? [];
  const colorRows = snapshot?.colors ?? [];
  const current = snapshot?.current ?? null;
  const top = 40 - VISIBLE_ROWS;
  const piece = pieceCells(current);
  const pieceSet = new Set(
    piece.filter(([, y]) => y >= top && y < 40).map(([x, y]) => `${x},${y}`),
  );

  const cells: JSX.Element[] = [];

  for (let visibleY = 0; visibleY < VISIBLE_ROWS; visibleY += 1) {
    const y = top + visibleY;
    const row = rows[y] ?? 0;
    for (let x = 0; x < BOARD_WIDTH; x += 1) {
      const occupied = boardOccupied(row, x);
      const isPiece = pieceSet.has(`${x},${y}`);
      const letter = colorRows[y]?.[x] ?? "";
      const lockedColor =
        letter && letter !== "." ? PIECE_COLORS[letter] ?? (letter === "G" ? "#6b7a8f" : "#3a4452") : "#3a4452";
      const color = isPiece ? PIECE_COLORS[current?.name ?? ""] ?? "#e6edf3" : occupied ? lockedColor : "#11161d";
      cells.push(
        <rect
          key={`${x}-${y}`}
          x={x * CELL + 1}
          y={visibleY * CELL + 1}
          width={CELL - 2}
          height={CELL - 2}
          rx={2}
          fill={color}
          opacity={isPiece ? 0.95 : occupied ? 0.9 : 1}
        />,
      );
    }
  }

  return (
    <div className="board-panel">
      <div className="board-header">
        <div>
          <div className="board-title">{label}</div>
          {subtitle && <div className="tiny muted">{subtitle}</div>}
        </div>
        {snapshot?.top_out && <span className="status status-failed">top out</span>}
      </div>
      <svg
        className="board-svg"
        viewBox={`0 0 ${BOARD_WIDTH * CELL} ${VISIBLE_ROWS * CELL}`}
        role="img"
        aria-label={`${label} board`}
      >
        <rect x={0} y={0} width={BOARD_WIDTH * CELL} height={VISIBLE_ROWS * CELL} fill="#0d1117" rx={3} />
        {cells}
      </svg>
    </div>
  );
}
