"""Run the experiment matrix and the evaluation protocol.

Examples:
    .venv/bin/python scripts/run_experiments.py --matrix main
    .venv/bin/python scripts/run_experiments.py --matrix ablations
    .venv/bin/python scripts/run_experiments.py --matrix evaluate --matches 40

Training runs are sequential here (each run already uses n_envs parallel
environments).  Use `--parallel N` to run several configs concurrently as
separate processes.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

PY = sys.executable

MATRICES: Dict[str, List[Dict[str, str]]] = {
    "main": [
        {"config": "configs/ppo_main.json", "run_id": "exp-ppo-main"},
        {"config": "configs/dqn_main.json", "run_id": "exp-dqn-main"},
    ],
    "ablations": [
        {"config": "configs/ablation_no_board_penalty.json", "run_id": "exp-ppo-noboard"},
        {"config": "configs/ablation_no_opponent_obs.json", "run_id": "exp-ppo-nooppobs"},
        {"config": "configs/ablation_s1_ruleset.json", "run_id": "exp-ppo-s1"},
        {"config": "configs/single_heuristic.json", "run_id": "exp-ppo-singleheur"},
        {"config": "configs/mixed_opponents.json", "run_id": "exp-ppo-mixed"},
    ],
}


def run_training(spec: Dict[str, str]) -> int:
    cmd = [PY, "-m", "tetrisrl", "train", "--config", spec["config"], "--run-id", spec["run_id"]]
    print("[matrix] running", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=REPO)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", choices=list(MATRICES) + ["all", "evaluate"], default="main")
    parser.add_argument("--matches", type=int, default=30)
    parser.add_argument("--opponents", type=str, default="random,heuristic,search")
    parser.add_argument("--parallel", type=int, default=1)
    args = parser.parse_args()

    if args.matrix == "evaluate":
        evaluate_all(args.matches, args.opponents)
        return

    specs: List[Dict[str, str]] = []
    if args.matrix in ("all", "main"):
        specs += MATRICES["main"]
    if args.matrix in ("all", "ablations"):
        specs += MATRICES["ablations"]
    if args.parallel <= 1:
        for spec in specs:
            run_training(spec)
    else:
        import concurrent.futures as cf

        with cf.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            list(pool.map(run_training, specs))


def evaluate_all(matches: int, opponents: str) -> None:
    from tetrisrl.training.experiment_manager import ExperimentManager
    from tetrisrl.evaluation.evaluator import evaluate_agent
    from tetrisrl.agents.policy_agent import PolicyAgent

    manager = ExperimentManager()
    out_dir = REPO / "results" / "evaluations"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for run in manager.list_runs():
        if not run["id"].startswith("exp-"):
            continue
        checkpoints = [c for c in manager.list_checkpoints(run["id"]) if Path(c["path"]).exists()]
        if not checkpoints:
            checkpoints = sorted(Path(run["results_dir"]).glob("checkpoints/*.pt"))
            checkpoints = [{"path": str(p), "timestep": int(p.stem.split("_")[-1])} for p in checkpoints]
        if not checkpoints:
            print(f"[evaluate] no checkpoint for {run['id']}")
            continue
        # Prefer the final checkpoint: the comparison is about where training
        # ended, not about a lucky mid-run evaluation.
        finals = [c for c in checkpoints if Path(c["path"]).name.startswith("final_")]
        if finals:
            chosen = max(finals, key=lambda c: c.get("timestep", 0))
        else:
            chosen = max(checkpoints, key=lambda c: (c.get("win_rate") or -1, c.get("timestep", 0)))
        path = chosen["path"] if isinstance(chosen, dict) else str(chosen)
        print(f"[evaluate] {run['id']} <- {path}", flush=True)
        agent = PolicyAgent.from_checkpoint(path)
        run_summary = {}
        for opponent in opponents.split(","):
            result = evaluate_agent(lambda: agent, opponent.strip(), n_matches=matches, seed=1234, max_pieces=500, ruleset="tetrio_s2")
            run_summary[opponent] = result["summary"]
            s = result["summary"]
            print(f"  vs {opponent}: win {s['win_rate']:.3f} [{s['win_rate_ci_low']:.3f},{s['win_rate_ci_high']:.3f}] n={s['matches']}", flush=True)
        summary[run["id"]] = {"checkpoint": path, "algorithm": run["algorithm"], "results": run_summary}
    path = out_dir / "evaluation_summary.json"
    path.write_text(json.dumps(summary, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
