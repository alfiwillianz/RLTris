/**
 * Tetromino geometry mirrored from tetrisrl/environment/pieces.py.
 *
 * Replays store a board bitmask plus the current piece's name/rotation/x/y.
 * Deriving the occupied cells here means playback never runs the Python engine
 * and never performs neural inference.
 */

type Cell = [number, number];

const SPAWN_MATRICES: Record<string, string[]> = {
  I: ["....", "XXXX", "....", "...."],
  J: ["X..", "XXX", "..."],
  L: ["..X", "XXX", "..."],
  O: ["XX", "XX"],
  S: [".XX", "XX.", "..."],
  T: [".X.", "XXX", "..."],
  Z: ["XX.", ".XX", "..."],
};

function rotateCW(matrix: string[]): string[] {
  const n = matrix.length;
  return Array.from({ length: n }, (_, y) =>
    Array.from({ length: n }, (_, x) => matrix[n - 1 - x][y]).join(""),
  );
}

function cellsFromMatrix(matrix: string[]): Cell[] {
  const cells: Cell[] = [];
  matrix.forEach((row, y) => {
    [...row].forEach((char, x) => {
      if (char === "X") cells.push([x, y]);
    });
  });
  return cells;
}

const CELLS: Record<string, Cell[][]> = {};
for (const [name, spawn] of Object.entries(SPAWN_MATRICES)) {
  const states: Cell[][] = [];
  let matrix = spawn;
  for (let rotation = 0; rotation < 4; rotation += 1) {
    states.push(cellsFromMatrix(matrix));
    matrix = rotateCW(matrix);
  }
  CELLS[name] = states;
}

export type PieceName = "I" | "J" | "L" | "O" | "S" | "T" | "Z";

export const PIECE_COLORS: Record<string, string> = {
  I: "#22d3ee",
  J: "#60a5fa",
  L: "#fb923c",
  O: "#facc15",
  S: "#4ade80",
  T: "#c084fc",
  Z: "#f87171",
};

export interface PiecePlacement {
  name: string;
  rotation: number;
  x: number;
  y: number;
}

/** Occupied board cells of a positioned piece (may include hidden rows). */
export function pieceCells(piece: PiecePlacement | null): Cell[] {
  if (!piece || !CELLS[piece.name]) return [];
  const rotation = ((piece.rotation % 4) + 4) % 4;
  return CELLS[piece.name][rotation].map(([x, y]) => [piece.x + x, piece.y + y]);
}

/** Bit i in each row corresponds to column i (bit 0 = left-most). */
export function boardOccupied(rowValue: number, column: number): boolean {
  return ((rowValue >> column) & 1) === 1;
}

export const VISIBLE_ROWS = 20;
export const BOARD_HEIGHT = 40;
export const BOARD_WIDTH = 10;
