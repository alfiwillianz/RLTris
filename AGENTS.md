# Project: TetrisRL
## Competitive Reinforcement Learning Arena | TETR.IO Season 2

You are an autonomous AI research engineering team operating under a lead agent. Build a complete, reproducible competitive Tetris reinforcement learning research project.

This is not a toy Tetris clone. The objective is to investigate whether reinforcement learning can develop competitive strategies against established Tetris algorithms.

The project must implement:
- PPO (Proximal Policy Optimization).
- Double DQN (Double Deep Q-Network).
- A competitive 1v1 arena.
- TETR.IO Season 2 mechanics.
- SRS+ rotation.
- Open-source algorithmic opponents.
- A persistent local Web UI for training monitoring, experiments, tournaments, and match replays.

Prioritize correctness, scientific reproducibility, modularity, and actual experimental evidence.

---

# 1. Mandatory Multi-Agent Development Workflow

You MUST use subagents. Do not attempt to implement the entire project sequentially as a single agent.

First inspect the available agent orchestration capabilities and determine how to delegate tasks using the installed coding environment.

Create a lead-agent/subagent workflow.

## Required subagent assignments

**Subagent 1: Ruleset Researcher**
- Research TETR.IO Season 2 mechanics.
- Investigate SRS+ rotation and kick tables.
- Research spin detection, All-Mini, B2B charging, surge, combos, garbage, and cancellation.
- Identify authoritative documentation and reference implementations.
- Produce docs/RULESET.md.
- Do not invent unverified rules.

**Subagent 2: Opponent Researcher**
- Discover open-source Tetris AI algorithms suitable for local integration.
- Investigate MisaMino/Zetris and Blockfish.
- Find additional alternatives to ZZZTOJ.
- Verify repositories, licenses, activity, dependencies, execution requirements, and game compatibility.
- Prioritize genuine competitive algorithms over simplistic heuristic agents.
- Produce docs/BENCHMARKS.md.

Important: ZZZTOJ is NOT an assumed available source-code dependency. Do not attempt to reverse-engineer, impersonate, scrape, or depend on a closed-source implementation.

Discover replacements autonomously. Candidate projects are not automatically accepted: verify that they are actually open-source, usable, and compatible.

**Subagent 3: Game Engine Engineer**
- Implement the deterministic Tetris game engine.
- Implement board state, piece generation, rotations, placement, locking, garbage, and versus interactions.
- Create unit tests.
- Do not implement RL algorithms inside the game engine.

**Subagent 4: RL Research Engineer**
- Implement PPO and Double DQN.
- Implement observation encoding and action masking.
- Implement reward shaping, training, checkpoints, and curriculum learning.
- Ensure both algorithms use the same game mechanics.

**Subagent 5: Web UI Engineer**
- Develop the local experiment dashboard.
- Implement persistent experiment tracking.
- Build training visualization, tournament comparisons, and match replay.
- Integrate with the training infrastructure through a documented API.

**Lead Agent**
- Coordinate all subagents.
- Establish shared interfaces and contracts before parallel implementation.
- Review subagent results.
- Resolve integration conflicts.
- Verify mechanics and tests.
- Run end-to-end experiments.
- Maintain TODO.md and project documentation.

## Parallelization requirements

Delegate independent research and implementation tasks concurrently wherever possible.

Do not have multiple agents edit the same critical files simultaneously.

Establish interfaces before assigning implementation tasks.

Require every subagent to report:
- Files created or modified.
- Implementation decisions.
- Tests executed.
- Test results.
- Known limitations.
- External sources used.

The lead agent must independently review critical game mechanics, RL integration, and benchmark claims.

If subagents are unavailable, document the limitation and continue with clearly separated work packages. Never falsely claim delegation occurred.

---

# 2. Project Research Objective

Primary research question:

Can reinforcement learning develop competitive Tetris strategies against established algorithmic opponents under TETR.IO Season 2 mechanics?

Secondary questions:

1. Does PPO outperform Double DQN?
2. Does opponent-aware observation improve win rate?
3. Does Season 2 B2B charging change learned attack strategies?
4. Can mixed-opponent training improve generalization?
5. How does reward shaping influence competitive behavior?

---

# 3. Game Rules and Environment

Target: TETR.IO Season 2 multiplayer mechanics with SRS+.

Implement and verify:

- 10-column board with 40 rows, including hidden rows.
- Seven-bag randomizer.
- Seven standard tetrominoes.
- SRS+ rotation and kick behavior.
- TETR.IO-specific 180-degree rotation.
- Hold.
- Hard drop.
- Piece previews.
- Lock delay and movement/rotation reset behavior.
- T-spin detection.
- All-Mini spin classification.
- Line-clear classification.
- Combo system.
- B2B charging.
- Surge accumulation and release.
- Garbage generation.
- Pending garbage queues.
- Garbage cancellation.
- Garbage insertion and hole generation.
- Top-out and victory conditions.

Verify exact Season 2 mechanics from authoritative documentation and reference implementations.

Do not silently substitute generic Guideline rules.

Document uncertainties and isolate configurable approximations.

Implement deterministic random seeds for both piece generation and garbage generation.

---

# 4. Game Engine Architecture

Suggested structure:

tetrisrl/
    environment/
        board.py
        pieces.py
        randomizer.py
        rotation.py
        lock_system.py
        spin_detection.py
        scoring.py
        garbage.py
        versus.py
        ruleset.py

    agents/
        base.py
        random_agent.py
        heuristic_agent.py
        ppo/
        dqn/
        opponents/

    training/
        train_ppo.py
        train_dqn.py
        curriculum.py
        self_play.py
        checkpoints.py
        experiment_manager.py

    evaluation/
        tournament.py
        metrics.py
        statistical_analysis.py
        match_replay.py

    visualization/
        arena.py
        renderer.py

    dashboard/
        backend/
        frontend/

    tests/
    configs/
    scripts/
    results/
    docs/

    README.md
    TODO.md
    requirements.txt
    pyproject.toml

Modify the structure when technically justified.

Separate simulation, learning, evaluation, persistence, and presentation.

---

# 5. Competitive Arena

Implement a local deterministic 1v1 versus simulator.

Both players have independent game states.

Implement:
- Independent boards.
- Independent piece sequences.
- Garbage queues.
- Attack generation.
- Garbage cancellation.
- Garbage insertion.
- Simultaneous interactions.
- Match termination.
- Match replay.

Use the same ruleset for both players.

The simulator must support:
- Headless training.
- Agent-versus-agent.
- Agent-versus-opponent.
- Human-versus-agent, if practical.

The simulator must remain independent of the graphical interface.

---

# 6. Opponent Discovery and Integration

Research open-source Tetris algorithms.

Initial candidates:
- MisaMino / Zetris.
- Blockfish.
- Additional alternatives discovered by the Opponent Researcher.

Do not assume all candidates support versus mode or TETR.IO mechanics.

For every candidate, establish:

1. Repository URL.
2. License.
3. Implementation language.
4. Build requirements.
5. Supported game mechanics.
6. Supported gameplay modes.
7. Integration feasibility.
8. Required compatibility adaptations.

Prioritize algorithms that provide genuine competitive decision-making, such as:
- Beam search.
- Multi-ply lookahead.
- Expectimax.
- Genetic optimization.
- Handcrafted evaluation functions.
- Other established Tetris search algorithms.

Implement a common opponent adapter interface:

- reset()
- observe()
- choose_action()
- receive_result()
- terminate()

Use subprocess adapters where appropriate.

If a benchmark uses a different ruleset:
- Document the differences.
- Avoid silently changing its behavior.
- Establish a compatible benchmark mode where possible.
- Clearly label approximate compatibility.

Never claim that an opponent is fully integrated until an actual match has been executed successfully.

Blockfish's Cheese Race/downstacking specialization must be identified as such. Do not misrepresent it as a general-purpose versus benchmark.

Provide at least:
- Random legal-placement baseline.
- Handcrafted heuristic baseline.
- One genuine search-based baseline.

---

# 7. Observation Space

Implement structured and tensor-based observations.

Own board:
- Occupancy grid.
- Column heights.
- Aggregate height.
- Number of holes.
- Surface bumpiness.

Piece information:
- Current piece.
- Hold piece.
- Hold availability.
- Configured next-piece preview.

Opponent information:
- Opponent board.
- Opponent heights.
- Pending garbage.
- Recent attack history.
- Recent incoming attack history.

Competitive state:
- Own pending garbage.
- Combo.
- B2B state and charge.
- Surge state.
- Recent line-clear information.

Only expose information that would be available to a real player.

Do not leak future randomizer information.

Document the observation schema.

---

# 8. Action Space

Use placement-based decisions.

The agent selects:
- Rotation.
- Horizontal placement.
- Hold decision.

The simulator executes the corresponding hard drop.

Implement valid-action enumeration and action masks.

PPO:
- Correct masked categorical distribution.
- Correct log-probabilities.
- Correct entropy calculation.

Double DQN:
- Mask invalid actions during exploration.
- Mask invalid actions during greedy selection.
- Mask invalid next-state actions during target calculation.

Document the action encoding.

---

# 9. Reinforcement Learning

## PPO

Implement using PyTorch.

Required:
- Actor-critic architecture.
- Clipped surrogate objective.
- Generalized Advantage Estimation.
- Value-function loss.
- Entropy regularization.
- Mini-batch optimization.
- Rollout collection.
- Gradient clipping.
- Checkpointing.
- TensorBoard or equivalent training metrics.

## Double DQN

Implement using PyTorch.

Required:
- Online Q-network.
- Target Q-network.
- Experience replay.
- Target synchronization.
- Epsilon-greedy exploration.
- Double Q-learning targets.
- Huber loss.
- Gradient clipping.
- Checkpointing.
- Training metrics.

## Shared infrastructure

Both algorithms must share:
- Environment.
- Observation representation.
- Action representation.
- Reward specification.
- Evaluation protocol.

Do not give one algorithm a privileged observation or different ruleset.

---

# 10. Reward Engineering

Implement configurable reward decomposition:

R = R_clear + R_attack + R_defense + R_survival + R_terminal - R_board_penalty

Consider:
- Lines cleared.
- Attack generated.
- Garbage cancelled.
- Downstacking.
- Difficult clears.
- T-spin bonuses.
- B2B maintenance.
- Combo maintenance.
- Aggregate height.
- Holes.
- Surface bumpiness.
- Top-out.
- Match victory or defeat.

Log every reward component separately.

Implement reward ablation experiments.

Do not assume that the initial reward weights are optimal.

---

# 11. Training Curriculum

Implement:

Stage 1: Basic survival.
- Random opponents.
- Low pressure.

Stage 2: Heuristic competition.
- Learn efficient placement and board management.

Stage 3: Search-based opponents.
- Integrate MisaMino/Zetris and other compatible engines.

Stage 4: Competitive pressure.
- Introduce garbage attacks and advanced mechanics.

Stage 5: Mixed-opponent training.
- Randomize opponents to reduce overfitting.

Stage 6: Self-play.
- Maintain historical checkpoints.
- Train against previous policy versions.

All curriculum stages must be configurable.

Training must support:
- Resume from checkpoint.
- Periodic checkpoint saving.
- Configurable episodes and timesteps.
- Multiple seeds.
- Parallel environments.
- Graceful interruption.
- Persistent training progress.

---

# 12. Web UI: Persistent Experiment Dashboard

This is a major deliverable, not an optional visualization.

Build a local Web application that allows the user to inspect results after extended training sessions.

Recommended stack:
- FastAPI backend.
- React + Vite frontend.
- SQLite experiment metadata.
- Filesystem-based checkpoints and replay storage.
- WebSocket or polling for live training updates.
- Pygame is reserved for optional standalone visualization, not required for the dashboard.

Use an alternative stack only if there is a clear technical advantage.

## A. Dashboard overview

Display:
- Total training runs.
- Active runs.
- Completed runs.
- Algorithm comparison.
- Best checkpoint.
- Latest tournament.
- Total training timesteps.
- Latest evaluation results.

## B. Training runs

Allow the user to:
- View all previous training runs.
- Start a new run.
- Inspect active runs.
- Stop a run safely.
- Resume an interrupted run.
- Compare configurations.
- View checkpoint history.

Each run must retain:
- Unique run ID.
- Algorithm.
- Configuration.
- Random seeds.
- Start/end timestamps.
- Training progress.
- Checkpoint locations.
- Evaluation metrics.
- Experiment notes.

## C. Live training visualization

Display:
- Episode reward.
- Moving average reward.
- Win rate.
- Episode length.
- Lines cleared.
- Attack efficiency.
- Average board height.
- Number of holes.
- Loss curves.
- PPO entropy.
- DQN epsilon.
- Learning rate.

Allow users to select metrics and training runs.

Charts must remain available after training finishes.

Do not rely on an in-memory frontend state as the only record of results.

## D. Algorithm comparison

Provide a comparison page for PPO and Double DQN.

Show:
- Training curves.
- Evaluation win rates.
- Lines cleared.
- Average survival.
- Attack efficiency.
- Garbage cancellation.
- Opponent-specific performance.
- Confidence intervals.

Allow selection of multiple runs and checkpoints.

## E. Tournament results

Provide:
- Opponent selection.
- Match scheduling.
- Tournament history.
- Win/loss statistics.
- Match duration.
- Performance breakdown.
- Exportable CSV results.

Support round-robin evaluation.

## F. Match replay

This is particularly important.

Record completed matches in a deterministic replay format.

The UI must allow the user to:
- Browse matches.
- Select a match.
- Watch both boards simultaneously.
- Play and pause.
- Change playback speed.
- Step forward/backward where practical.
- Inspect attack events.
- Inspect garbage queues.
- Inspect line clears.
- Inspect B2B and surge events.
- View the final match statistics.

A replay must reproduce the recorded match without rerunning neural network inference.

Store sufficient game events and state information to make playback reliable.

## G. Checkpoint management

Allow users to:
- Browse saved checkpoints.
- Inspect training step and evaluation performance.
- Compare checkpoints.
- Select a checkpoint for evaluation.
- Export checkpoint metadata.

Do not automatically overwrite the best checkpoint.

## H. Dashboard execution

Provide:

python -m tetrisrl dashboard

The command should launch the backend and provide the local dashboard URL.

Also provide separate commands for backend and frontend development.

The dashboard must be usable after the training process exits.

Persist all experiment information in SQLite and all large artifacts on disk.

Include a simple setup and startup guide.

---

# 13. Evaluation and Experiments

Metrics:
- Win rate.
- Loss rate.
- Draw rate.
- Match duration.
- Pieces placed.
- Lines cleared.
- Attack per minute.
- Pieces per second.
- Attack efficiency.
- Garbage cancelled.
- Incoming garbage survived.
- Aggregate height.
- Number of holes.
- Top-out frequency.
- B2B frequency.
- Combo statistics.
- Surge utilization.

Use paired seeds and controlled starting conditions.

Calculate confidence intervals and report sample sizes.

Experiments:

A. PPO versus Double DQN.

B. Reward shaping ablation.

C. Single-opponent versus mixed-opponent training.

D. Opponent observation ablation.

E. Season 2 B2B charging and surge strategy.

F. Sample efficiency and convergence.

G. Generalization to previously unseen opponents.

Do not fabricate training results or statistical significance.

---

# 14. Testing

Test:
- Board representation.
- Piece generation.
- Seven-bag distribution.
- SRS+ transitions.
- Wall kicks.
- Floor kicks.
- 180-degree rotations.
- Collision detection.
- Locking.
- Line clearing.
- Spin detection.
- Combo and B2B.
- Surge.
- Garbage cancellation.
- Garbage insertion.
- Top-out.
- Simultaneous versus interactions.
- Deterministic replay.
- Action masks.
- PPO probability calculations.
- Double DQN target masking.
- Training checkpoint restoration.
- Dashboard persistence.
- Replay playback.

Do not begin long training until the core mechanics pass automated tests.

---

# 15. Hardware and Performance

Target hardware:
- AMD Ryzen 5 7500F.
- NVIDIA RTX 5060 Ti 16 GB.
- 32 GB system RAM.
- Linux.

Requirements:
- Automatic CUDA detection.
- GPU neural-network training.
- CPU headless simulation.
- Configurable parallel environments.
- Memory-efficient replay buffers.
- Configurable worker counts.
- Simulation throughput benchmarking.

Avoid unnecessarily large models.

Correctness comes before optimization.

---

# 16. Documentation

Create:

README.md
TODO.md
docs/RULESET.md
docs/ARCHITECTURE.md
docs/BENCHMARKS.md
docs/EXPERIMENTS.md
docs/REPRODUCIBILITY.md
docs/DASHBOARD.md

Document:
- Ruleset sources.
- Opponent sources and licenses.
- Integration limitations.
- Algorithm implementations.
- Experimental methodology.
- Dashboard architecture.
- Installation.
- Training.
- Evaluation.
- Replay.
- Known limitations.

---

# 17. CLI

Provide:

python -m tetrisrl train --algorithm ppo
python -m tetrisrl train --algorithm dqn

python -m tetrisrl evaluate --algorithm ppo
python -m tetrisrl evaluate --algorithm dqn

python -m tetrisrl tournament

python -m tetrisrl play --agent ppo

python -m tetrisrl replay --file results/match.json

python -m tetrisrl benchmark

python -m tetrisrl dashboard

Support configuration files, seeds, checkpoints, and experiment IDs.

---

# 18. Development Milestones

Use the following order.

Milestone 1:
Research ruleset and benchmark algorithms. Produce documentation.

Milestone 2:
Establish interfaces and project architecture.

Milestone 3:
Implement deterministic game engine.

Milestone 4:
Implement automated mechanics tests.

Milestone 5:
Implement versus interactions and replay recording.

Milestone 6:
Implement random and heuristic agents.

Milestone 7:
Implement PPO and Double DQN.

Milestone 8:
Implement benchmark adapters.

Milestone 9:
Implement training and curriculum.

Milestone 10:
Implement persistent experiment tracking.

Milestone 11:
Implement Web UI.

Milestone 12:
Run smoke tests and short training experiments.

Milestone 13:
Run full experiments and tournaments.

Milestone 14:
Produce plots, reports, and documentation.

After every milestone:
- Run relevant tests.
- Update TODO.md.
- Record concrete outputs.
- Report blockers.
- Preserve a runnable state.

Use subagents continuously where tasks can be parallelized.

---

# 19. Final Deliverables

The finished project must contain:

1. TETR.IO Season 2 simulation.
2. SRS+ implementation.
3. Competitive versus arena.
4. PPO implementation.
5. Double DQN implementation.
6. Open-source opponent adapters.
7. Random and heuristic baselines.
8. Training curriculum.
9. Persistent experiment database.
10. Local Web UI.
11. Live training visualization.
12. Algorithm comparison dashboard.
13. Tournament system.
14. Deterministic match replay.
15. Checkpoint management.
16. Reproducible experiments.
17. Statistical evaluation.
18. Technical documentation.
19. Actual experimental findings.

# Final Instructions

This is an engineering and research project.

Never:
- Fabricate opponent integrations.
- Invent verified rules.
- Fabricate training results.
- Claim tests passed without running them.
- Claim subagents completed work they did not perform.
- Treat surrogate algorithms as actual external benchmarks.
- Lose experiment results when training terminates.

The dashboard must remain useful after multiple days of training and across separate application sessions.

Start by inspecting the environment, available subagent capabilities, and working directory.

Delegate research tasks immediately.

Establish interfaces before parallel implementation.

Work incrementally, validate every milestone, and keep the project reproducible.

The final objective is a legitimate competitive reinforcement learning research platform, not merely a Tetris clone with a neural network attached.
