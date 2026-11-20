import type { ReplaySnapshot } from "../types";
import { BOARD_WIDTH, PIECE_COLORS, VISIBLE_ROWS, boardOccupied, pieceCells } from "../lib/tetris";

interface BoardProps {
  snapshot: ReplaySnapshot | null;
  label: string;
  subtitle?: string;
}

const CELL = 20;
const GARBAGE_W = 8;
const GARBAGE_GAP = 6;
const BOARD_X = GARBAGE_W + GARBAGE_GAP;
const BOARD_W = BOARD_WIDTH * CELL;
const BOARD_H = VISIBLE_ROWS * CELL;

const MINI_SHAPES: Record<string, [number, number][]> = {
  I: [[0, 1], [1, 1], [2, 1], [3, 1]],
  J: [[0, 0], [0, 1], [1, 1], [2, 1]],
  L: [[2, 0], [0, 1], [1, 1], [2, 1]],
  O: [[1, 0], [2, 0], [1, 1], [2, 1]],
  S: [[1, 0], [2, 0], [0, 1], [1, 1]],
  T: [[1, 0], [0, 1], [1, 1], [2, 1]],
  Z: [[0, 0], [1, 0], [1, 1], [2, 1]],
};

export function MiniPiece({ name, size = 7 }: { name: string | null | undefined; size?: number }) {
  if (!name || !MINI_SHAPES[name]) {
    return <span className="mini-piece-empty">—</span>;
  }
  const cells = MINI_SHAPES[name];
  const color = PIECE_COLORS[name] ?? "#94a3b8";
  const w = 4 * size;
  const h = 2 * size;
  return (
    <svg
      className="mini-piece-svg"
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label={name}
    >
      {cells.map(([cx, cy]) => (
        <rect
          key={`${cx}-${cy}`}
          x={cx * size + 0.5}
          y={cy * size + 0.5}
          width={size - 1}
          height={size - 1}
          rx={1}
          fill={color}
        />
      ))}
    </svg>
  );
}

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
        letter && letter !== "." ? PIECE_COLORS[letter] ?? (letter === "G" ? "#525b6e" : "#3a4452") : "#3a4452";
      const fill = isPiece ? PIECE_COLORS[current?.name ?? ""] ?? "#edf0f5" : occupied ? lockedColor : null;
      if (!fill) continue;
      const px = BOARD_X + x * CELL;
      const py = visibleY * CELL;
      cells.push(
        <g key={`${x}-${y}`}>
          <rect
            x={px + 0.75}
            y={py + 0.75}
            width={CELL - 1.5}
            height={CELL - 1.5}
            rx={1.5}
            fill={fill}
            opacity={isPiece ? 0.98 : 0.9}
          />
          <rect
            x={px + 1.5}
            y={py + 1.5}
            width={CELL - 3}
            height={2.5}
            rx={0.5}
            fill="#ffffff"
            opacity={isPiece ? 0.28 : 0.16}
          />
        </g>,
      );
    }
  }

  const pending = Math.max(0, Math.min(VISIBLE_ROWS, snapshot?.pending_garbage ?? 0));
  const garbageSegments: JSX.Element[] = [];
  for (let i = 0; i < pending; i += 1) {
    const sy = BOARD_H - (i + 1) * CELL;
    garbageSegments.push(
      <rect
        key={`g-${i}`}
        x={1}
        y={sy + 1}
        width={GARBAGE_W - 2}
        height={CELL - 2}
        rx={1}
        fill={pending >= 8 ? "#ef4444" : "#f59e0b"}
      />,
    );
  }

  const gridLines: JSX.Element[] = [];
  for (let x = 1; x < BOARD_WIDTH; x += 1) {
    gridLines.push(
      <line
        key={`vx-${x}`}
        x1={BOARD_X + x * CELL}
        y1={0}
        x2={BOARD_X + x * CELL}
        y2={BOARD_H}
        stroke="#151821"
        strokeWidth={1}
      />,
    );
  }
  for (let y = 1; y < VISIBLE_ROWS; y += 1) {
    gridLines.push(
      <line
        key={`hy-${y}`}
        x1={BOARD_X}
        y1={y * CELL}
        x2={BOARD_X + BOARD_W}
        y2={y * CELL}
        stroke="#151821"
        strokeWidth={1}
      />,
    );
  }

  return (
    <div className="board-panel">
      <div className="board-header">
        <div>
          <div className="board-title">{label}</div>
          {subtitle && <div className="tiny muted mono">{subtitle}</div>}
        </div>
        {snapshot?.top_out && <span className="status status-failed">top out</span>}
      </div>
      <svg
        className="board-svg"
        viewBox={`0 0 ${BOARD_X + BOARD_W} ${BOARD_H}`}
        role="img"
        aria-label={`${label} board`}
      >
        <rect x={0} y={0} width={GARBAGE_W} height={BOARD_H} fill="#0c0e13" stroke="#1e222d" strokeWidth={1} rx={2} />
        {garbageSegments}
        <rect x={BOARD_X} y={0} width={BOARD_W} height={BOARD_H} fill="#08090c" stroke="#242834" strokeWidth={1} rx={2} />
        {gridLines}
        {cells}
      </svg>
    </div>
  );
}
