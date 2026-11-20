"""Command line interface: ``python -m tetrisrl <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _add_common_train_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--algorithm", choices=["ppo", "dqn"])
    p.add_argument("--mode", choices=["rl", "pretrain"], default=None)
    p.add_argument("--config", type=str, default=None, help="YAML/JSON training config")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--timesteps", type=int, default=None)
    p.add_argument("--n-envs", type=int, default=None)
    p.add_argument("--vec-env", choices=["dummy", "subprocess", "batched"], default=None)
    p.add_argument("--run-id", type=str, default=None)
    p.add_argument("--resume", type=str, default=None, help="checkpoint path to resume from")
    p.add_argument("--stage", type=str, default=None, help="run only one curriculum stage by name")
    p.add_argument("--notes", type=str, default="")
    p.add_argument("--db", type=str, default=None, help="SQLite path (default: results/tetrisrl.sqlite3)")
    p.add_argument("--include-opponent", dest="include_opponent", action="store_true", default=None)
    p.add_argument("--no-opponent-observation", dest="include_opponent", action="store_false")
    p.add_argument("--max-pieces", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tetrisrl", description="Competitive Tetris RL arena (TETR.IO Season 2 mechanics)")
    parser.add_argument("--version", action="store_true", help="print version")
    sub = parser.add_subparsers(dest="command")

    p_train = sub.add_parser("train", help="train PPO or Double DQN")
    _add_common_train_args(p_train)
    p_train.add_argument("--device", type=str, default="auto")

    p_eval = sub.add_parser("evaluate", help="evaluate a checkpoint or algorithm")
    p_eval.add_argument("--algorithm", choices=["ppo", "dqn"], default="ppo")
    p_eval.add_argument("--checkpoint", type=str, default=None)
    p_eval.add_argument("--opponents", type=str, default="random,heuristic")
    p_eval.add_argument("--matches", type=int, default=20)
    p_eval.add_argument("--seed", type=int, default=0)
    p_eval.add_argument("--max-pieces", type=int, default=1000)
    p_eval.add_argument("--ruleset", type=str, default="tetrio_s2")
    p_eval.add_argument("--db", type=str, default=None)
    p_eval.add_argument("--json-out", type=str, default=None)
    p_eval.add_argument("--run-id", type=str, default=None, help="attach results to a training run")

    p_tour = sub.add_parser("tournament", help="run a round-robin tournament")
    p_tour.add_argument("--config", type=str, default=None, help="JSON tournament config")
    p_tour.add_argument("--participants", type=str, default="random,heuristic,search")
    p_tour.add_argument("--seeds", type=int, default=3, help="matches per pairing")
    p_tour.add_argument("--max-pieces", type=int, default=1000)
    p_tour.add_argument("--seed", type=int, default=0)
    p_tour.add_argument("--name", type=str, default="round-robin")
    p_tour.add_argument("--db", type=str, default=None)
    p_tour.add_argument("--replay-dir", type=str, default="results/replays")
    p_tour.add_argument("--csv", type=str, default=None)
    p_tour.add_argument("--workers", type=int, default=4, help="parallel match processes (1 = sequential)")

    p_play = sub.add_parser("play", help="play against an agent in the terminal")
    p_play.add_argument("--agent", type=str, default="heuristic", help="random|heuristic|search|ppo:<ckpt>|dqn:<ckpt>")
    p_play.add_argument("--seed", type=int, default=0)
    p_play.add_argument("--max-pieces", type=int, default=1000)
    p_play.add_argument("--ruleset", type=str, default="tetrio_s2")

    p_replay = sub.add_parser("replay", help="inspect and verify a replay file")
    p_replay.add_argument("--file", type=str, required=True)
    p_replay.add_argument("--verify", action="store_true")
    p_replay.add_argument("--summary", action="store_true")
    p_replay.add_argument("--json", action="store_true", help="print machine-readable summary")

    p_bench = sub.add_parser("benchmark", help="measure simulation throughput")
    p_bench.add_argument("--steps", type=int, default=5000)
    p_bench.add_argument("--seed", type=int, default=0)
    p_bench.add_argument("--json", action="store_true")

    p_dash = sub.add_parser("dashboard", help="launch the local experiment dashboard")
    p_dash.add_argument("--host", type=str, default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8000)
    p_dash.add_argument("--dev", action="store_true")
    p_dash.add_argument("--open", action="store_true")
    p_dash.add_argument("--db", type=str, default=None)

    return parser


# ---------------------------------------------------------------------------
def cmd_train(args) -> int:
    from .config import TrainConfig
    from .training.experiment_manager import ExperimentManager
    from .training.run_runner import run_training

    manager = ExperimentManager(args.db)
    config = TrainConfig.load(args.config) if args.config else TrainConfig()
    if args.algorithm:
        config.algorithm = args.algorithm
    if args.mode:
        config.mode = args.mode
    if args.seed is not None:
        config.seed = args.seed
    if args.timesteps is not None:
        config.timesteps = args.timesteps
    if args.n_envs is not None:
        config.n_envs = args.n_envs
    if args.vec_env:
        config.vec_env = args.vec_env
    if args.stage:
        config.stage = args.stage
    if args.include_opponent is not None:
        config.include_opponent = args.include_opponent
    if args.max_pieces is not None:
        config.max_pieces = args.max_pieces
    if args.device:
        config.device = args.device

    run_id = args.run_id
    if run_id is None:
        run = manager.create_run(config.algorithm, config.to_dict(), seed=config.seed, notes=args.notes or "")
        run_id = run["id"]
    elif manager.get_run(run_id) is None:
        manager.create_run(config.algorithm, config.to_dict(), seed=config.seed, run_id=run_id, notes=args.notes or "")
    else:
        manager.update_run(run_id, config_json=json.dumps(config.to_dict()), seed=config.seed)
    config.save(Path(f"results/runs/{run_id}") / "config.json")
    print(f"[tetrisrl] run_id={run_id} algorithm={config.algorithm} timesteps={config.timesteps}")
    run_training(config, run_id, manager=manager, resume_checkpoint=args.resume, notes=args.notes or "")
    return 0


def _load_policy(algorithm: str, checkpoint: Optional[str], db: Optional[str]):
    from .agents.policy_agent import PolicyAgent
    from .training.experiment_manager import ExperimentManager

    if checkpoint:
        return PolicyAgent.from_checkpoint(checkpoint)
    manager = ExperimentManager(db)
    ckpts = manager.list_checkpoints(limit=200)
    candidates = [c for c in ckpts if c["path"].endswith(".pt") and c["run_id"].startswith(algorithm)]
    if not candidates:
        raise SystemExit(f"no {algorithm} checkpoints found in the experiment database; train first or pass --checkpoint")
    return PolicyAgent.from_checkpoint(candidates[0]["path"])


def cmd_evaluate(args) -> int:
    from .evaluation.evaluator import evaluate_agent
    from .evaluation.experiment import save_evaluation
    from .training.experiment_manager import ExperimentManager

    agent = _load_policy(args.algorithm, args.checkpoint, args.db)
    opponents = [o.strip() for o in args.opponents.split(",") if o.strip()]
    results: Dict[str, Any] = {}
    manager = ExperimentManager(args.db)
    for opponent in opponents:
        result = evaluate_agent(
            lambda: agent,
            opponent,
            n_matches=args.matches,
            seed=args.seed,
            max_pieces=args.max_pieces,
            ruleset=args.ruleset,
        )
        results[opponent] = result["summary"]
        if args.run_id:
            manager.log_metrics(args.run_id, 0, {f"eval/win_rate_{opponent}": result["summary"]["win_rate"]})
        summary = result["summary"]
        print(
            f"{opponent:>12}: win {summary['win_rate']:.3f} "
            f"[{summary['win_rate_ci_low']:.3f}, {summary['win_rate_ci_high']:.3f}] "
            f"n={summary['matches']} lines={summary['lines']:.1f} apm={summary['attack_per_minute']:.1f}"
        )
    out = {"algorithm": args.algorithm, "checkpoint": args.checkpoint, "results": results}
    if args.json_out:
        path = save_evaluation(out, args.json_out)
        print(f"saved {path}")
    return 0


def cmd_tournament(args) -> int:
    from .evaluation.experiment import run_tournament_and_persist

    if args.config:
        data = json.loads(Path(args.config).read_text())
        participants = data.get("participants")
        seeds = int(data.get("seeds", args.seeds))
        max_pieces = int(data.get("max_pieces", args.max_pieces))
        name = data.get("name", args.name)
        ruleset = data.get("ruleset", "tetrio_s2")
    else:
        specs = [s.strip() for s in args.participants.split(",") if s.strip()]
        participants = [{"name": s, "spec": s} for s in specs]
        seeds, max_pieces, name, ruleset = args.seeds, args.max_pieces, args.name, "tetrio_s2"
    result = run_tournament_and_persist(
        participants,
        n_seeds=seeds,
        max_pieces=max_pieces,
        ruleset=ruleset,
        seed=args.seed,
        name=name,
        db=args.db,
        replay_dir=args.replay_dir,
        csv_path=args.csv,
        workers=args.workers,
    )
    for row in result["standings"]:
        print(f"{row['name']:>12}: {row['wins']}W-{row['losses']}L-{row['draws']}D  win={row['win_rate']:.2f}")
    print(f"tournament_id={result['tournament_id']}")
    return 0


def cmd_play(args) -> int:
    from .agents import make_agent
    from .environment.engine import GameState
    from .environment.versus import VersusMatch

    opponent = make_agent(args.agent, seed=args.seed + 1)
    env = GameState(seed=args.seed, max_pieces=args.max_pieces)
    print("Enter placements as: rotation column [h]   (rotation 0-3, column 0-9, optional h = hold)")
    print("Example: 0 4      -> rotate 0, place with left-most cell in column 4")
    while not env.finished:
        for line in env.board.visible_strings():
            print(line.replace(".", " .").replace("#", "[]"))
        print(
            f"piece={env.current.name if env.current else '?'} hold={env.hold} next={''.join(env.preview(5))} "
            f"combo={env.combo} b2b={env.b2b_active} pending={env.pending_garbage}"
        )
        raw = input("> ").strip()
        if raw in ("q", "quit", "exit"):
            break
        parts = raw.split()
        try:
            rotation, column = int(parts[0]), int(parts[1])
            hold = len(parts) > 2 and parts[2].lower().startswith("h")
            action = rotation * 20 + column * 2 + (1 if hold else 0)
        except (ValueError, IndexError):
            print("invalid input; expected: rotation column [h]")
            continue
        result = env.apply_action(action)
        if not result.valid:
            print("illegal placement")
            continue
        print(
            f"placed {result.piece} lines={result.lines} spin={result.spin} "
            f"attack={result.sent} cancelled={result.cancelled} garbage_in={result.garbage_inserted}"
        )
        if result.top_out:
            print(f"YOU TOPPED OUT ({result.topped_out_reason})")
            break
    print("final board:")
    for line in env.board.visible_strings():
        print(line)
    return 0


def cmd_replay(args) -> int:
    from .evaluation.match_replay import load_replay, replay_summary, verify_replay_file

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"replay not found: {path}")
    summary = replay_summary(load_replay(path))
    if args.verify:
        ok = verify_replay_file(path)
        summary["verified"] = ok
        print(f"replay verification: {'PASS' if ok else 'FAIL'}")
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"match {summary['match_id']}  agents={summary['agents']}  ticks={summary['ticks']}")
        print(f"winner={summary['winner']} reason={summary['reason']} frames={summary['frames']}")
        for i, stats in enumerate(summary["stats"]):
            print(f"  player {chr(97+i)}: {json.dumps(stats)}")
    return 0


def cmd_benchmark(args) -> int:
    import time

    from .agents import make_agent
    from .environment.env import EnvConfig, VersusEnv

    env = VersusEnv(
        "tetrio_s2",
        opponent=make_agent("random", seed=args.seed + 1),
        seed=args.seed,
        config=EnvConfig(max_pieces=10_000, solo=False),
    )
    obs, info = env.reset()
    steps = 0
    t0 = time.time()
    while steps < args.steps:
        mask = env.action_mask()
        action = next(i for i, ok in enumerate(mask) if ok)
        obs, reward, terminated, truncated, info = env.step(action)
        steps += 1
        if terminated or truncated:
            env.reset()
    elapsed = time.time() - t0
    result = {
        "steps": steps,
        "seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "observation_size": env.observation_size,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['steps_per_second']:,.0f} steps/s ({steps} steps in {elapsed:.2f}s)")
    return 0


def cmd_dashboard(args) -> int:
    from .dashboard.server import run_dashboard

    run_dashboard(host=args.host, port=args.port, open_browser=args.open, dev=args.dev, db_path=args.db)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from . import __version__

        print(__version__)
        return 0
    if args.command is None:
        parser.print_help()
        return 1
    handlers = {
        "train": cmd_train,
        "evaluate": cmd_evaluate,
        "tournament": cmd_tournament,
        "play": cmd_play,
        "replay": cmd_replay,
        "benchmark": cmd_benchmark,
        "dashboard": cmd_dashboard,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
