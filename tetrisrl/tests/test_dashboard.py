"""Tests for the FastAPI dashboard backend.

The suite uses a temporary SQLite database (the same schema owner used by
training: ``ExperimentManager``) and a temporary artifact directory.  No npm,
no training process, and no network access are required.

Covers: overview counters, run list/detail, metric downsampling, compare,
checkpoints, tournaments list/detail/CSV, replay fetch, the missing-trainer
failure path for POST /api/runs, process control without a real trainer, 404s,
websocket events, and persistence/orphan recovery across app instances.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from tetrisrl.dashboard.backend import app as app_module
from tetrisrl.dashboard.backend.app import create_app
from tetrisrl.training.experiment_manager import ExperimentManager


def _snapshot() -> Dict[str, Any]:
    return {
        "rows": [0] * 40,
        "current": {"name": "T", "rotation": 0, "x": 3, "y": 20},
        "hold": "I",
        "next": ["S", "Z", "L"],
        "combo": 0,
        "b2b": False,
        "b2b_charge": 0.0,
        "surge": 0,
        "pending_garbage": 0,
        "lines": 0,
        "attack": 0,
        "pieces": 0,
        "top_out": False,
    }


def _player_stats() -> Dict[str, Any]:
    return {
        "pieces": 1,
        "lines": 0,
        "attack": 0,
        "attack_sent": 0,
        "cancelled": 0,
        "garbage_received": 0,
        "garbage_inserted": 0,
        "four_lines": 0,
        "tspins": 0,
        "mini_tspins": 0,
        "perfect_clears": 0,
        "max_combo": 0,
        "max_b2b": 0,
        "surges": 0,
        "holds": 0,
        "top_out_reason": "block_out",
        "final_height": 20,
        "final_holes": 0,
    }


def _replay(match_id: str) -> Dict[str, Any]:
    snapshot = _snapshot()
    return {
        "version": 1,
        "match_id": match_id,
        "ruleset": "tetrio_s2",
        "seed": 0,
        "seeds": {"a_piece": 1, "b_piece": 2, "a_garbage": 3, "b_garbage": 4},
        "max_pieces": 2,
        "agents": {"a": "random", "b": "heuristic"},
        "metadata": {"tournament_id": "tour-1"},
        "ticks": [
            {
                "t": 0,
                "a": {"action": 0, "piece": "T", "lines": 0, "attack": 0, "sent": 0},
                "b": {"action": 2, "piece": "I", "lines": 1, "attack": 1, "sent": 1},
            },
            {
                "t": 1,
                "a": {"action": 1, "piece": "S", "lines": 0, "attack": 0, "sent": 0},
                "b": {"action": 4, "piece": "O", "lines": 4, "attack": 4, "sent": 4},
            },
        ],
        "frames": [{"a": snapshot, "b": snapshot}, {"a": snapshot, "b": snapshot}],
        "result": {
            "winner": 1,
            "reason": "top_out_a",
            "ticks": 2,
            "stats": [_player_stats(), _player_stats()],
            "final_hashes": [0, 0],
            "invalid_actions": [0, 0],
        },
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    results = tmp_path / "results"
    results.mkdir()
    db_path = tmp_path / "dashboard.sqlite3"
    monkeypatch.setenv("TETRISRL_DB", str(db_path))
    monkeypatch.setenv("TETRISRL_RESULTS_DIR", str(results))
    manager = ExperimentManager(str(db_path))

    # --- completed PPO run with a dense metric series -------------------
    ppo_dir = results / "runs" / "ppo-1"
    manager.create_run(
        "ppo",
        config={"lr": 0.0003, "batch_size": 64},
        seed=11,
        name="ppo seed 11",
        notes="seeded test run",
        results_dir=str(ppo_dir),
        run_id="ppo-1",
        status="starting",
    )
    manager.set_status("ppo-1", "running")
    for timestep in range(0, 1000, 10):
        manager.log_metrics(
            "ppo-1",
            timestep,
            {
                "train/reward": timestep / 100.0,
                "eval/win_rate": min(0.95, 0.2 + timestep / 2000.0),
                "train/loss": 1.0 / (1.0 + timestep),
            },
        )
    checkpoint_path = results / "checkpoints" / "ppo-990.pt"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_bytes(b"not-a-real-checkpoint")
    manager.add_checkpoint(
        "ppo-1",
        str(checkpoint_path),
        990,
        mean_reward=12.5,
        win_rate=0.62,
        metadata={"opponents": {"random": 0.9, "heuristic": 0.55}},
    )
    manager.update_run("ppo-1", best_checkpoint=str(checkpoint_path))
    manager.set_status("ppo-1", "completed")

    # --- completed DQN run ----------------------------------------------
    dqn_dir = results / "runs" / "dqn-1"
    manager.create_run(
        "dqn",
        config={"lr": 0.001},
        seed=22,
        name="dqn seed 22",
        results_dir=str(dqn_dir),
        run_id="dqn-1",
        status="completed",
    )
    for timestep in range(0, 500, 10):
        manager.log_metrics(
            "dqn-1",
            timestep,
            {"train/reward": timestep / 200.0, "eval/win_rate": 0.4},
        )
    manager.update_run("dqn-1", total_timesteps=490)

    # --- tournament + match + replay on disk ----------------------------
    replay_path = results / "replays" / "tour-1-m000-s0.json"
    replay_path.parent.mkdir(parents=True)
    replay_path.write_text(json.dumps(_replay("tour-1-m000-s0")), encoding="utf-8")
    manager.create_tournament(
        "Seeded cup",
        config={"participants": ["random", "heuristic"], "seeds": [0], "max_pieces": 2},
        tournament_id="tour-1",
        status="completed",
    )
    manager.add_match(
        "tour-1-m000-s0",
        "random",
        "heuristic",
        winner=1,
        reason="top_out_a",
        ticks=2,
        seed=0,
        replay_path=str(replay_path),
        stats={"players": [_player_stats(), _player_stats()]},
        tournament_id="tour-1",
    )
    manager.update_tournament(
        "tour-1",
        status="completed",
        results={
            "standings": [
                {
                    "rank": 1,
                    "participant": "heuristic",
                    "matches": 1,
                    "wins": 1,
                    "losses": 0,
                    "draws": 0,
                    "points": 1.0,
                    "score": 1.0,
                    "ticks": 2,
                },
                {
                    "rank": 2,
                    "participant": "random",
                    "matches": 1,
                    "wins": 0,
                    "losses": 1,
                    "draws": 0,
                    "points": 0.0,
                    "score": 0.0,
                    "ticks": 2,
                },
            ],
            "matches": [],
            "limitations": [],
            "seeds": [0],
            "max_pieces": 2,
        },
        csv_path=str(results / "tournaments" / "tour-1.csv"),
    )

    app = create_app(str(db_path))
    with TestClient(app) as client:
        yield {
            "client": client,
            "app": app,
            "manager": manager,
            "db_path": str(db_path),
            "results": results,
            "checkpoint_path": str(checkpoint_path),
            "replay": _replay("tour-1-m000-s0"),
        }


# ---------------------------------------------------------------------------
# Meta / static
# ---------------------------------------------------------------------------
def test_health(env: Dict[str, Any]) -> None:
    response = env["client"].get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db_path"] == env["db_path"]
    assert "trainer_available" in body


def test_static_spa_and_client_route(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    # Either the built SPA or the friendly build-instructions page.
    assert "root" in root.text or "TetrisRL" in root.text

    deep_link = client.get("/replays/tour-1-m000-s0")
    assert deep_link.status_code == 200
    assert "text/html" in deep_link.headers["content-type"]

    missing_api = client.get("/api/definitely-not-a-route")
    assert missing_api.status_code == 404
    assert missing_api.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# Overview / runs
# ---------------------------------------------------------------------------
def test_overview_counters(env: Dict[str, Any]) -> None:
    response = env["client"].get("/api/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["total_runs"] == 2
    assert body["active_runs"] == 0
    assert body["completed_runs"] == 2
    assert body["total_timesteps"] >= 1480
    assert body["by_algorithm"] == {"ppo": 1, "dqn": 1}
    assert body["best"]["id"] == "ppo-1"
    assert body["latest_tournament"]["id"] == "tour-1"
    assert body["latest_evaluations"]["ppo"]["run_id"] == "ppo-1"
    assert body["latest_evaluations"]["dqn"]["run_id"] == "dqn-1"


def test_runs_list_and_detail(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    body = client.get("/api/runs").json()
    assert {run["id"] for run in body["runs"]} == {"ppo-1", "dqn-1"}
    assert all(isinstance(run["config"], dict) for run in body["runs"])

    filtered = client.get("/api/runs?algorithm=ppo").json()["runs"]
    assert [run["id"] for run in filtered] == ["ppo-1"]

    status_filtered = client.get("/api/runs?status=completed").json()["runs"]
    assert {run["id"] for run in status_filtered} == {"ppo-1", "dqn-1"}

    detail = client.get("/api/runs/ppo-1").json()
    assert detail["algorithm"] == "ppo"
    assert detail["seed"] == 11
    assert detail["notes"] == "seeded test run"
    assert detail["config"]["lr"] == 0.0003
    assert detail["best_checkpoint"] == env["checkpoint_path"]


def test_run_404s(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/metrics").status_code == 404
    assert client.get("/api/runs/nope/checkpoints").status_code == 404
    assert client.post("/api/runs/nope/stop").status_code == 404
    assert client.post("/api/runs/nope/resume").status_code == 404


# ---------------------------------------------------------------------------
# Metrics / compare / checkpoints
# ---------------------------------------------------------------------------
def test_metrics_downsampling(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    full = client.get("/api/runs/ppo-1/metrics").json()
    assert set(full["names"]) == {"train/reward", "eval/win_rate", "train/loss"}
    full_points = full["metrics"]["train/reward"]
    assert len(full_points) == 100
    assert full_points[0][0] == 0 and full_points[-1][0] == 990

    downsampled = client.get("/api/runs/ppo-1/metrics?max_points=25").json()
    points = downsampled["metrics"]["train/reward"]
    assert len(points) == 25
    assert points[0][0] == 0
    assert points[-1][0] == 990

    selected = client.get("/api/runs/ppo-1/metrics?names=eval/win_rate").json()
    assert selected["names"] == ["eval/win_rate"]
    assert set(selected["metrics"].keys()) == {"eval/win_rate"}

    empty = client.get("/api/runs/ppo-1/metrics?names=,").json()
    assert empty == {"metrics": {}, "names": []}


def test_metrics_push(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    response = client.post(
        "/api/runs/ppo-1/metrics",
        json={"timestep": 1000, "metrics": {"train/reward": 12.5, "eval/win_rate": 0.7}},
    )
    assert response.status_code == 200
    body = client.get("/api/runs/ppo-1/metrics?names=train/reward").json()
    assert body["metrics"]["train/reward"][-1] == [1000, 12.5]
    assert client.get("/api/runs/ppo-1").json()["total_timesteps"] == 1000


def test_compare(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    response = client.get("/api/compare?run_ids=ppo-1,dqn-1&metric=train/reward&max_points=10")
    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "train/reward"
    assert [run["run_id"] for run in body["runs"]] == ["ppo-1", "dqn-1"]
    assert [run["algorithm"] for run in body["runs"]] == ["ppo", "dqn"]
    assert all(len(run["series"]) <= 10 for run in body["runs"])
    assert all(run["series"] for run in body["runs"])

    missing = client.get("/api/compare?run_ids=ppo-1,nope&metric=train/reward")
    assert missing.status_code == 404

    no_metric = client.get("/api/compare?run_ids=ppo-1&metric=does/not/exist").json()
    assert no_metric["runs"][0]["series"] == []


def test_checkpoints(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    global_body = client.get("/api/checkpoints").json()
    assert len(global_body["checkpoints"]) == 1
    checkpoint = global_body["checkpoints"][0]
    assert checkpoint["run_id"] == "ppo-1"
    assert checkpoint["timestep"] == 990
    assert checkpoint["metadata"]["opponents"]["heuristic"] == 0.55

    by_run = client.get("/api/runs/ppo-1/checkpoints").json()
    assert by_run["checkpoints"][0]["id"] == "ppo-1@990"
    assert client.get("/api/runs/dqn-1/checkpoints").json()["checkpoints"] == []

    filtered = client.get("/api/checkpoints?run_id=dqn-1").json()
    assert filtered["checkpoints"] == []


# ---------------------------------------------------------------------------
# Tournaments
# ---------------------------------------------------------------------------
def test_tournaments_list_detail_csv(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    listing = client.get("/api/tournaments").json()["tournaments"]
    assert len(listing) == 1
    assert listing[0]["id"] == "tour-1"
    assert listing[0]["config"]["participants"] == ["random", "heuristic"]
    assert listing[0]["results"]["standings"][0]["participant"] == "heuristic"

    detail = client.get("/api/tournaments/tour-1").json()
    assert detail["tournament"]["id"] == "tour-1"
    assert len(detail["matches"]) == 1
    assert detail["matches"][0]["agent_b"] == "heuristic"

    csv_response = client.get("/api/tournaments/tour-1/csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "match_id" in csv_response.text
    assert "tour-1-m000-s0" in csv_response.text
    assert "heuristic" in csv_response.text

    assert client.get("/api/tournaments/nope").status_code == 404
    assert client.get("/api/tournaments/nope/csv").status_code == 404


def test_create_tournament_runs_real_match(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    response = client.post(
        "/api/tournaments",
        json={"name": "Tiny live cup", "participants": ["random", "heuristic"], "seeds": 1, "max_pieces": 6},
    )
    assert response.status_code == 200
    tournament_id = response.json()["tournament"]["id"]
    assert response.json()["tournament"]["status"] in ("running", "completed")

    deadline = time.time() + 30
    detail: Dict[str, Any] = {}
    while time.time() < deadline:
        detail = client.get(f"/api/tournaments/{tournament_id}").json()
        if detail["tournament"]["status"] != "running":
            break
        time.sleep(0.1)
    assert detail["tournament"]["status"] == "completed", detail["tournament"].get("results")
    assert len(detail["matches"]) == 1  # one round-robin pairing
    match_id = detail["matches"][0]["id"]
    replay = client.get(f"/api/matches/{match_id}/replay")
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["frames"]
    assert replay_body["ticks"]
    assert replay_body["result"]["winner"] in (0, 1, None)
    assert "limitations" in detail["tournament"]["config"]


# ---------------------------------------------------------------------------
# Replays
# ---------------------------------------------------------------------------
def test_replays_and_replay_fetch(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    listing = client.get("/api/replays").json()["replays"]
    assert len(listing) == 1
    entry = listing[0]
    assert entry["id"] == "tour-1-m000-s0"
    assert entry["available"] is True
    assert entry["replay_url"] == "/api/matches/tour-1-m000-s0/replay"

    response = client.get("/api/matches/tour-1-m000-s0/replay")
    assert response.status_code == 200
    assert response.json() == env["replay"]
    assert len(response.json()["frames"]) == 2

    assert client.get("/api/matches/nope/replay").status_code == 404


def test_replay_missing_file(env: Dict[str, Any]) -> None:
    manager: ExperimentManager = env["manager"]
    manager.add_match(
        "missing-replay",
        "random",
        "random",
        winner=None,
        reason="draw",
        ticks=0,
        seed=0,
        replay_path=str(env["results"] / "replays" / "does-not-exist.json"),
        tournament_id="tour-1",
    )
    response = env["client"].get("/api/matches/missing-replay/replay")
    assert response.status_code == 404
    missing = next(
        replay for replay in env["client"].get("/api/replays").json()["replays"] if replay["id"] == "missing-replay"
    )
    assert missing["available"] is False


# ---------------------------------------------------------------------------
# Run control / process supervision
# ---------------------------------------------------------------------------
def test_start_run_missing_train_module(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "_train_module_available", lambda: False)
    client: TestClient = env["client"]
    response = client.post(
        "/api/runs",
        json={
            "algorithm": "ppo",
            "seed": 7,
            "config": {"lr": 0.001, "timesteps": 50},
            "notes": "unit test run",
            "timesteps": 50,
        },
    )
    assert response.status_code == 200  # must not 500
    body = response.json()
    assert body["spawned"] is False
    assert body["run"]["status"] == "failed"
    assert "train" in (body["error"] or "").lower()

    run_id = body["run"]["id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "failed"
    assert detail["error"]

    config_path = Path(detail["results_dir"]) / "config.json"
    assert config_path.is_file()
    assert json.loads(config_path.read_text()) == {"lr": 0.001, "timesteps": 50}


def test_start_run_spawn_command(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    client: TestClient = env["client"]
    manager: ExperimentManager = env["manager"]
    captured: Dict[str, Any] = {}

    def fake_start(run_id: str, argv: list[str], env: Dict[str, str] | None = None, cwd: str | None = None) -> int:
        captured["argv"] = list(argv)
        captured["env"] = dict(env or {})
        manager.set_status(run_id, "running")
        manager.update_run(run_id, pid=424242)
        return 424242

    monkeypatch.setattr(app_module, "_train_module_available", lambda: True)
    monkeypatch.setattr(client.app.state.jobs, "start", fake_start)

    response = client.post(
        "/api/runs",
        json={
            "algorithm": "dqn",
            "seed": 5,
            "config": {"lr": 0.0005, "device": "cpu"},
            "notes": "hello notes",
            "timesteps": 1234,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["spawned"] is True
    run = body["run"]
    assert run["status"] == "running"
    assert run["pid"] == 424242

    argv = captured["argv"]
    assert argv[1:4] == ["-m", "tetrisrl", "train"]
    assert "--algorithm" in argv and argv[argv.index("--algorithm") + 1] == "dqn"
    assert "--run-id" in argv and argv[argv.index("--run-id") + 1] == run["id"]
    assert "--seed" in argv and argv[argv.index("--seed") + 1] == "5"
    assert "--config" in argv and Path(argv[argv.index("--config") + 1]).is_file()
    assert "--timesteps" in argv and argv[argv.index("--timesteps") + 1] == "1234"
    assert "--notes" in argv and argv[argv.index("--notes") + 1] == "hello notes"
    assert "--device" in argv and argv[argv.index("--device") + 1] == "cpu"
    assert captured["env"]["TETRISRL_DB"] == env["db_path"]


def test_stop_run(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    manager: ExperimentManager = env["manager"]
    manager.create_run("ppo", seed=3, results_dir=str(env["results"] / "runs" / "stoppable"), run_id="stoppable", status="running")
    manager.update_run("stoppable", pid=None)

    response = client.post("/api/runs/stoppable/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "stopped"
    assert body["stop"]["was_running"] is False

    # Stopping an already finished run is a conflict, not a crash.
    assert client.post("/api/runs/ppo-1/stop").status_code == 409


def test_resume_requires_checkpoint_and_spawns(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    client: TestClient = env["client"]
    manager: ExperimentManager = env["manager"]

    no_checkpoint = client.post("/api/runs/dqn-1/resume")
    assert no_checkpoint.status_code == 400

    captured: Dict[str, Any] = {}

    def fake_start(run_id: str, argv: list[str], env: Dict[str, str] | None = None, cwd: str | None = None) -> int:
        captured["argv"] = list(argv)
        manager.set_status(run_id, "running")
        manager.update_run(run_id, pid=5150)
        return 5150

    monkeypatch.setattr(app_module, "_train_module_available", lambda: True)
    monkeypatch.setattr(client.app.state.jobs, "start", fake_start)

    response = client.post("/api/runs/ppo-1/resume")
    assert response.status_code == 200
    body = response.json()
    assert body["spawned"] is True
    assert body["run"]["status"] == "running"
    assert body["checkpoint"] == env["checkpoint_path"]
    argv = captured["argv"]
    assert "--resume" in argv and argv[argv.index("--resume") + 1] == env["checkpoint_path"]
    assert "--run-id" in argv and argv[argv.index("--run-id") + 1] == "ppo-1"


def test_job_manager_tracks_and_terminates_real_process(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    manager: ExperimentManager = env["manager"]
    jobs = client.app.state.jobs
    manager.create_run(
        "ppo",
        seed=0,
        results_dir=str(env["results"] / "runs" / "sleeper"),
        run_id="sleeper",
        status="starting",
    )
    pid = jobs.start(
        "sleeper",
        [sys.executable, "-c", "import time; time.sleep(60)"],
        env=os.environ.copy(),
    )
    try:
        assert jobs.is_running("sleeper")
        assert client.get("/api/runs/sleeper").json()["status"] == "running"
        response = client.post("/api/runs/sleeper/stop")
        assert response.status_code == 200
        assert response.json()["run"]["status"] == "stopped"
        assert response.json()["stop"]["was_running"] is True
        assert not jobs.is_running("sleeper")
    finally:
        jobs.stop("sleeper", grace=1.0)


# ---------------------------------------------------------------------------
# Websocket
# ---------------------------------------------------------------------------
def test_websocket_hello_and_metric_broadcast(env: Dict[str, Any]) -> None:
    client: TestClient = env["client"]
    with client.websocket_connect("/ws/training") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        client.app.state.bus.publish(
            {"type": "metric", "run_id": "ppo-1", "timestep": 5, "metrics": {"train/reward": 1.5}}
        )
        event = websocket.receive_json()
        assert event["type"] == "metric"
        assert event["run_id"] == "ppo-1"
        assert event["timestep"] == 5


# ---------------------------------------------------------------------------
# Persistence / orphan recovery
# ---------------------------------------------------------------------------
def test_persistence_and_orphan_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = tmp_path / "results"
    results.mkdir()
    db_path = tmp_path / "persist.sqlite3"
    monkeypatch.setenv("TETRISRL_DB", str(db_path))
    monkeypatch.setenv("TETRISRL_RESULTS_DIR", str(results))
    manager = ExperimentManager(str(db_path))
    manager.create_run("ppo", seed=1, run_id="done", results_dir=str(results / "runs" / "done"), status="completed")
    manager.log_metrics("done", 100, {"eval/win_rate": 0.5})
    manager.create_run("dqn", seed=2, run_id="orphan", results_dir=str(results / "runs" / "orphan"), status="running")
    manager.update_run("orphan", pid=2_147_483_646)  # no live process

    first_app = create_app(str(db_path))
    with TestClient(first_app) as first_client:
        assert first_client.get("/api/runs/done").json()["status"] == "completed"
        assert first_client.get("/api/runs/orphan").json()["status"] == "stale"

    # A brand new app instance (fresh process simulation) sees the same data.
    second_app = create_app(str(db_path))
    with TestClient(second_app) as second_client:
        overview = second_client.get("/api/overview").json()
        assert overview["total_runs"] == 2
        assert overview["completed_runs"] == 1
        assert second_client.get("/api/runs/done").json()["status"] == "completed"
        assert second_client.get("/api/runs/orphan").json()["status"] == "stale"
        metrics = second_client.get("/api/runs/done/metrics").json()
        assert metrics["metrics"]["eval/win_rate"] == [[100, 0.5]]
