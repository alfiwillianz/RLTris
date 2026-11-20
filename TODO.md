# TODO / project status

Live status of the TetrisRL build. Milestones follow `AGENTS.md` §18.

## Completed

- [x] M1 Research: verified TETR.IO Season 2 ruleset (`docs/RULESET.md`, 840 lines,
      citations + confidence labels + uncertainties table) and open-source opponent
      survey (`docs/BENCHMARKS.md`, licences/verdicts/integration paths).
- [x] M2 Interfaces + architecture (`docs/ARCHITECTURE.md`): action encoding (80),
      engine API, observation schema, reward components, DB schema, dashboard API, CLI.
- [x] M3 Deterministic engine: board, SRS/SRS+ kick tables incl. 180°, seven-bag,
      hold, hard drop, spin detection, Season 2 attack/combo/B2B charging/Surge,
      garbage queue + tank + cancellation + hole RNG, top-out modes.
- [x] M4 Automated mechanics tests: board, geometry, kicks, bag, scoring, garbage,
      spins, top-out, determinism, action masks, observation, rewards, replay.
- [x] M5 Versus arena + deterministic replay + hash verification.
- [x] M6 Baselines: random, handcrafted heuristic, beam-search (multi-ply).
- [x] M7 PPO and Double DQN (masked distributions, GAE, Double-Q target masking,
      Huber loss, checkpoints) with 22 dedicated RL tests.
- [x] M9 Training: curriculum, vectorised envs, evaluation with CIs, checkpoints,
      resume, graceful stop, SQLite metric persistence.
- [x] M10 Persistent experiment tracking (`training/experiment_manager.py`).
- [x] M11 Dashboard backend + React/Vite frontend (see `docs/DASHBOARD.md`).
- [x] CLI: train / evaluate / tournament / play / replay / benchmark / dashboard.

## In progress / remaining

- [x] External engine integration: Cold Clear 2 (pinned commit ed8b193) built and driven
      over TBP for 20 real ranked matches (10-0-0 vs heuristic, 10-0-0 vs random),
      962 suggestions / 958 accepted (0.42% fallbacks). See `docs/BENCHMARKS_INTEGRATION.md`.
- [x] Dashboard end-to-end verification: live API returned real run metrics/tournaments,
      replay endpoint served recorded matches, POST /api/runs spawned and completed a real run.
- [ ] Full experiment matrix results and report (`docs/EXPERIMENTS.md`, `docs/RESULTS.md`).
- [ ] Plots (learning curves, win rates with CIs) generated from the SQLite DB.
- [ ] Optional: self-play stage using historical checkpoints (curriculum stage 6).

- [x] Engine research: nine repositories audited source-level (licences, SRS+/180,
      Season 2 coverage, headless, RL-vs-opponent role, integration complexity).
      See `docs/ENGINE_RESEARCH.md`; no project is both legally reusable and
      Season 2-complete, so the in-repo engine stays authoritative.

## Known blockers / limitations

- GPU driver required a reboot after a failed suspend/resume (`-EIO` on device open);
  CPU fallback works but training is slower.
- No external engine implements TETR.IO Season 2 attack/charging; all external
  engines are placement suggesters only, and the arena owns the ruleset.
- Exact garbage messiness / charge-base constants are unpublished; isolated as config.
