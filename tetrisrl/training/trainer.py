"""Shared training run context: persistence, evaluation, checkpointing, stop.

Both PPO and Double DQN use this context so run bookkeeping, evaluation
protocol, checkpoint naming, and dashboard metrics are identical.
"""

from __future__ import annotations

import json
import signal
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ..agents import make_agent
from ..agents.policy_agent import PolicyAgent
from ..environment.env import EnvConfig, VersusEnv
from ..environment.observation import ObservationEncoder
from ..environment.rewards import RewardConfig
from ..environment.ruleset import load_ruleset
from ..evaluation.evaluator import evaluate_agent
from ..training.checkpoints import save_checkpoint
from ..training.curriculum import Stage, build_opponent
from ..training.experiment_manager import ExperimentManager, utcnow


class RunContext:
    def __init__(
        self,
        config,
        run_id: str,
        manager: Optional[ExperimentManager] = None,
        resume_checkpoint: Optional[str] = None,
    ) -> None:
        self.config = config
        self.run_id = run_id
        self.manager = manager or ExperimentManager()
        self.run = self.manager.get_run(run_id)
        if self.run is None:
            self.run = self.manager.create_run(
                algorithm=config.algorithm,
                config=config.to_dict(),
                seed=config.seed,
                results_dir=f"results/runs/{run_id}",
                run_id=run_id,
                status="created",
                env={"python": "3.12", "torch_device": config.device},
            )
        self.run_dir = Path(self.run.get("results_dir") or f"results/runs/{run_id}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        config.save(self.run_dir / "config.json")
        self.resume_checkpoint = resume_checkpoint
        self.stop_requested = False
        self.start_time = time.time()
        self.best_win_rate = -1.0
        self.best_checkpoint: Optional[str] = None
        self._installed_signals: Dict[int, Any] = {}

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self.manager.set_status(self.run_id, "running")
        self.manager.update_run(self.run_id, pid=__import__("os").getpid())

    def finish(self, status: str = "completed", error: Optional[str] = None) -> None:
        self.manager.set_status(self.run_id, status, error=error)

    def install_signal_handlers(self) -> None:
        def handler(signum, frame):  # type: ignore[no-untyped-def]
            self.stop_requested = True
            print(f"\n[tetrisrl] received signal {signum}: stopping gracefully...", flush=True)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._installed_signals[sig] = signal.getsignal(sig)
                signal.signal(sig, handler)
            except Exception:
                pass

    def restore_signal_handlers(self) -> None:
        for sig, old in self._installed_signals.items():
            try:
                signal.signal(sig, old)
            except Exception:
                pass

    # -- logging -----------------------------------------------------------
    def log(self, step: int, metrics: Dict[str, float], print_msg: Optional[str] = None) -> None:
        clean = {k: float(v) for k, v in metrics.items() if v is not None and np.isfinite(float(v))}
        if clean:
            self.manager.log_metrics(self.run_id, step, clean)
        if print_msg:
            elapsed = max(1e-9, time.time() - self.start_time)
            print(f"[{self.run_id}] step {step:,} | {print_msg} | {step/elapsed:,.0f} steps/s", flush=True)

    def total_steps(self) -> int:
        run = self.manager.get_run(self.run_id) or {}
        return int(run.get("total_timesteps") or 0)

    # -- environments ------------------------------------------------------
    def observation_schema(self) -> Dict[str, Any]:
        return {
            "include_opponent": bool(self.config.include_opponent),
            "preview": int(self.config.preview),
            "height": 40,
            "width": 10,
            "max_pieces": int(self.config.max_pieces),
            "version": 1,
        }

    def make_encoder(self) -> ObservationEncoder:
        schema = self.observation_schema()
        return ObservationEncoder(
            include_opponent=schema["include_opponent"],
            preview=schema["preview"],
            height=schema["height"],
            width=schema["width"],
            max_pieces=schema["max_pieces"],
        )

    def reward_config(self, stage: Optional[Stage] = None) -> RewardConfig:
        data = dict(self.config.reward or {})
        if stage is not None:
            data.update(stage.reward_overrides or {})
        return RewardConfig.from_dict(data)

    def make_env(self, stage: Stage, seed: int) -> VersusEnv:
        ruleset_name = stage.ruleset or self.config.ruleset
        opponent = build_opponent(stage, seed)
        env_cfg = EnvConfig(
            max_pieces=stage.max_pieces,
            solo=stage.opponent in ("none", "solo", ""),
            pressure_interval=stage.pressure_interval,
            pressure_lines=stage.pressure_lines,
            preview=self.config.preview,
            include_opponent_observation=self.config.include_opponent,
        )
        return VersusEnv(
            ruleset=load_ruleset(ruleset_name),
            opponent=opponent,
            seed=seed,
            reward_config=self.reward_config(stage),
            encoder=self.make_encoder(),
            config=env_cfg,
        )

    # -- evaluation --------------------------------------------------------
    def evaluate(
        self,
        agent: Any,
        step: int,
        matches: Optional[int] = None,
        opponents: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        matches = matches or self.config.eval_matches
        opponents = opponents or list(self.config.eval_opponents)
        encoder = self.make_encoder()
        metrics: Dict[str, float] = {}
        win_rates = []
        for opponent in opponents:
            def factory(agent=agent, encoder=encoder) -> PolicyAgent:
                return PolicyAgent(agent, encoder, name=f"eval-{agent.__class__.__name__}")

            result = evaluate_agent(
                factory,
                opponent,
                n_matches=matches,
                seed=self.config.seed + step,
                max_pieces=max(500, self.config.max_pieces),
                ruleset=self.config.ruleset,
            )
            summary = result["summary"]
            key = opponent.replace(":", "_")
            metrics[f"eval/win_rate_{key}"] = summary["win_rate"]
            metrics[f"eval/win_rate_ci_low_{key}"] = summary["win_rate_ci_low"]
            metrics[f"eval/win_rate_ci_high_{key}"] = summary["win_rate_ci_high"]
            metrics[f"eval/lines_{key}"] = summary["lines"]
            metrics[f"eval/attack_per_minute_{key}"] = summary["attack_per_minute"]
            metrics[f"eval/attack_efficiency_{key}"] = summary["attack_efficiency"]
            metrics[f"eval/pieces_{key}"] = summary["pieces"]
            metrics[f"eval/holes_{key}"] = summary["avg_final_holes"]
            metrics[f"eval/height_{key}"] = summary["avg_final_height"]
            metrics[f"eval/garbage_cancelled_{key}"] = summary["garbage_cancelled"]
            metrics[f"eval/top_out_rate_{key}"] = summary["top_out_rate"]
            win_rates.append(summary["win_rate"])
            (self.run_dir / "eval").mkdir(parents=True, exist_ok=True)
            (self.run_dir / "eval" / f"eval_{step}_{key}.json").write_text(json.dumps(result, indent=1))
        metrics["eval/win_rate"] = sum(win_rates) / len(win_rates) if win_rates else 0.0
        metrics["eval/n_matches"] = float(matches * len(opponents))
        metrics["eval/step"] = float(step)
        return metrics

    # -- checkpoints -------------------------------------------------------
    def save(self, agent: Any, step: int, metrics: Optional[Dict[str, float]] = None, tag: str = "step") -> Path:
        path = save_checkpoint(
            agent,
            self.run_dir,
            step,
            algorithm=self.config.algorithm,
            config=self.config.to_dict(),
            observation=self.observation_schema(),
            metrics=metrics or {},
            tag=tag,
        )
        win_rate = None
        if metrics:
            win_rate = metrics.get("eval/win_rate")
        self.manager.add_checkpoint(
            self.run_id,
            str(path),
            step,
            mean_reward=(metrics or {}).get("train/episode_reward"),
            win_rate=win_rate,
            metadata={"metrics": {k: v for k, v in (metrics or {}).items() if k.startswith("eval/")}},
        )
        if win_rate is not None and win_rate > self.best_win_rate:
            self.best_win_rate = win_rate
            # Best checkpoints are separate files and are never overwritten.
            best_path = path.parent / f"best_{step:09d}.pt"
            best_path.write_bytes(path.read_bytes())
            self.best_checkpoint = str(best_path)
            self.manager.update_run(self.run_id, best_checkpoint=str(best_path))
        return path

    def log_system(self, step: int) -> None:
        try:
            import torch

            if torch.cuda.is_available():
                self.log(step, {
                    "system/gpu_mem_allocated_mb": torch.cuda.memory_allocated() / 1e6,
                    "system/gpu_mem_reserved_mb": torch.cuda.memory_reserved() / 1e6,
                })
        except Exception:
            pass

    def fail(self, error: str) -> None:
        self.manager.set_status(self.run_id, "failed", error=error)

    # -- training position (for resume) ------------------------------------
    def save_training_state(self, step: int, stage_index: int, stage_step: int) -> None:
        state = {
            "step": int(step),
            "stage_index": int(stage_index),
            "stage_step": int(stage_step),
            "algorithm": self.config.algorithm,
            "updated_at": utcnow(),
        }
        (self.run_dir / "training_state.json").write_text(json.dumps(state, indent=2))

    def load_training_state(self) -> Dict[str, int]:
        path = self.run_dir / "training_state.json"
        if not path.exists():
            return {"step": 0, "stage_index": 0, "stage_step": 0}
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return {"step": 0, "stage_index": 0, "stage_step": 0}
        return {
            "step": int(data.get("step", 0)),
            "stage_index": int(data.get("stage_index", 0)),
            "stage_step": int(data.get("stage_step", 0)),
        }
