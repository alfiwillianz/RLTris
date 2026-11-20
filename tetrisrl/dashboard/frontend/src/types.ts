export interface Run {
  id: string;
  name?: string | null;
  algorithm: string;
  status: string;
  config: Record<string, unknown>;
  env: Record<string, unknown>;
  seed: number | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
  updated_at?: string | null;
  notes?: string | null;
  total_timesteps: number;
  best_checkpoint?: string | null;
  results_dir?: string | null;
  pid?: number | null;
  error?: string | null;
}

export interface Checkpoint {
  id: string;
  run_id: string;
  path: string;
  timestep: number;
  created_at: string;
  mean_reward: number | null;
  win_rate: number | null;
  metadata: Record<string, unknown>;
}

export interface Overview {
  total_runs: number;
  active_runs: number;
  completed_runs: number;
  failed_runs: number;
  total_timesteps: number;
  by_algorithm: Record<string, number>;
  best: { id: string; best_checkpoint: string | null; algorithm: string } | null;
  latest_tournament: { id: string; name: string; created_at: string; status: string } | null;
  latest_evaluations: Record<string, { run_id: string; timestep: number; value: number }>;
  db_path?: string;
}

export type MetricSeries = Record<string, [number, number][]>;

export interface MetricsResponse {
  metrics: MetricSeries;
  names: string[];
}

export interface CompareRun {
  run_id: string;
  name?: string | null;
  algorithm: string;
  status: string;
  series: [number, number][];
}

export interface CompareResponse {
  metric: string;
  names: string[];
  runs: CompareRun[];
}

export interface Tournament {
  id: string;
  name: string;
  created_at: string;
  config: {
    participants?: string[];
    seeds?: number[];
    max_pieces?: number;
    ruleset?: string;
    limitations?: string[];
    [key: string]: unknown;
  };
  status: string;
  results: TournamentResults | null;
  csv_path?: string | null;
}

export interface Standing {
  rank: number;
  participant: string;
  matches: number;
  wins: number;
  losses: number;
  draws: number;
  points: number;
  score: number | null;
  ticks: number;
}

export interface TournamentMatch {
  id: string;
  seed: number;
  agent_a: string;
  agent_b: string;
  winner: number | null;
  reason: string;
  ticks: number;
  replay_path?: string | null;
  stats?: Record<string, unknown>[] | null;
}

export interface TournamentResults {
  standings?: Standing[];
  matches?: TournamentMatch[];
  limitations?: string[];
  failures?: string[];
  seeds?: number[];
  max_pieces?: number;
  error?: string;
}

export interface Match {
  id: string;
  tournament_id?: string | null;
  created_at: string;
  agent_a: string;
  agent_b: string;
  winner: number | null;
  reason: string;
  ticks: number;
  seed: number;
  replay_path?: string | null;
  stats: Record<string, unknown>;
}

export interface ReplayListItem extends Match {
  match_id?: string;
  available: boolean;
  replay_url: string;
}

export interface ReplaySnapshot {
  rows: number[];
  /** 40 strings of 10 chars: piece letter, "G" garbage, "." empty. */
  colors?: string[] | null;
  current: { name: string; rotation: number; x: number; y: number } | null;
  hold: string | null;
  next: string[];
  combo: number;
  b2b: boolean;
  b2b_charge: number;
  surge: number;
  pending_garbage: number;
  lines: number;
  attack: number;
  pieces: number;
  top_out: boolean;
}

export interface ReplayTickSide {
  action: number;
  type?: string;
  piece?: string;
  rotation?: number;
  column?: number;
  x?: number;
  y?: number;
  hold?: boolean;
  lines?: number;
  cleared_rows?: number[];
  spin?: boolean;
  mini?: boolean;
  perfect_clear?: boolean;
  attack?: number;
  cancelled?: number;
  sent?: number;
  garbage_inserted?: number;
  garbage_events?: Record<string, unknown>[];
  top_out?: boolean;
  top_out_reason?: string;
  clear?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ReplayTick {
  t: number;
  a: ReplayTickSide;
  b: ReplayTickSide;
}

export interface ReplayPlayerStats {
  pieces: number;
  lines: number;
  attack: number;
  attack_sent: number;
  cancelled: number;
  garbage_received: number;
  garbage_inserted: number;
  four_lines: number;
  tspins: number;
  mini_tspins: number;
  perfect_clears: number;
  max_combo: number;
  max_b2b: number;
  surges: number;
  holds: number;
  top_out_reason: string;
  final_height: number;
  final_holes: number;
}

export interface Replay {
  version: number;
  match_id: string;
  ruleset: Record<string, unknown> | string;
  seed: number;
  seeds?: Record<string, number>;
  max_pieces?: number;
  agents: { a: string; b: string };
  metadata?: Record<string, unknown>;
  ticks: ReplayTick[];
  frames: { a: ReplaySnapshot; b: ReplaySnapshot }[];
  result: {
    winner: number | null;
    reason: string;
    ticks: number;
    stats: ReplayPlayerStats[];
    final_hashes: number[];
    invalid_actions?: number[];
  };
}

export interface Health {
  status: string;
  version: string;
  db_path: string;
  results_root: string;
  static_available: boolean;
  trainer_available: boolean;
  tracked_jobs: number;
  tournaments_running: number;
}


export interface ParticipantOption {
  id: string;
  label: string;
  kind: "baseline" | "external" | "checkpoint";
  available: boolean;
  detail?: string | null;
  algorithm?: string;
  timestep?: number;
  run_id?: string;
  win_rate?: number | null;
}

export interface ParticipantsResponse {
  builtin: ParticipantOption[];
  checkpoints: ParticipantOption[];
}
