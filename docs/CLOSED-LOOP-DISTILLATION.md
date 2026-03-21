# Closed-Loop Iterative Distillation — Implementation Roadmap

> **Goal:** Create a feedback loop where the PPO self-play agent exports its game decisions
> as JSONL files, which the supervised training pipeline incorporates alongside Forge
> heuristic data. The supervised baseline gradually improves as the RL agent discovers
> better play patterns — the RL agent teaches the supervised model.

---

## Phase 1 — PPO Decision Exporter

**Goal:** PPO self-play writes decisions in the same JSONL format as Forge batch sims.

- [ ] Add a `DecisionExporter` class in `ml/training/self_play.py` that captures each
      (state, action, reward, game_context) during PPO rollouts
- [ ] Write to `data/results/ml-decisions-ppo-{batch_id}.jsonl` using the exact same
      schema as the Forge `DecisionSnapshot` files
- [ ] Include metadata fields to distinguish PPO-generated data:
  - `"source": "ppo"`
  - `"model_version"`
  - `"reward"`
  - `"episode_return"`
- [ ] Only export decisions from **winning** games initially (higher signal-to-noise)

**Files touched:** `ml/training/self_play.py`, new `ml/training/decision_exporter.py`

---

## Phase 2 — Dataset Builder Source Awareness

**Goal:** `dataset_builder.py` can ingest both Forge and PPO decision files with
configurable mixing.

- [ ] Update `build_dataset()` to scan for both `ml-decisions-sim-*.jsonl` (Forge) and
      `ml-decisions-ppo-*.jsonl` (PPO) files
- [ ] Add a `source_weights` config param — e.g., `{"forge": 1.0, "ppo": 0.5}` — to
      control sampling ratios so PPO data doesn't overwhelm the Forge baseline early on
- [ ] Add a `min_reward_threshold` filter for PPO data — only include decisions from
      games above a certain reward score
- [ ] Tag each sample with its source for downstream analysis

**Files touched:** `ml/data/dataset_builder.py`, `ml/config/scope.py`

---

## Phase 3 — Quality Gate & Validation

**Goal:** Prevent bad PPO data from degrading the supervised model.

- [ ] Add a validation split in `dataset_builder.py` (hold out 10-15% of Forge data as
      a fixed eval set)
- [ ] After each supervised training run, evaluate on the held-out Forge set — if
      accuracy drops below a threshold compared to the previous model, reject the PPO
      data batch
- [ ] Track win rate of the PPO agent — only export decisions once the PPO model exceeds
      a configurable win rate (e.g., >30% in 4-player pods, above the 25% random baseline)
- [ ] Log data quality metrics: action distribution entropy, reward distribution of
      exported games

**Files touched:** `ml/training/trainer.py`, `ml/eval/`, new `ml/data/quality_gate.py`

---

## Phase 4 — Distillation Loop Orchestrator

**Goal:** Automate the full cycle: supervised train -> PPO self-play -> export -> retrain.

- [ ] New `ml/training/distillation_loop.py` that orchestrates:
  1. Supervised train on current dataset (Forge + any existing PPO data)
  2. Run N episodes of PPO self-play using the new supervised model as starting policy
  3. Export winning PPO decisions to JSONL
  4. Quality gate check
  5. If passed, merge into dataset and go to step 1
  6. If failed, discard PPO batch, adjust hyperparameters, retry
- [ ] Add `max_iterations` and `convergence_check` (stop if win rate plateaus across
      iterations)
- [ ] Each iteration is a "generation" — tag data and models with generation number

**Files touched:** new `ml/training/distillation_loop.py`, `ml/config/scope.py`

---

## Phase 5 — UI Integration & Monitoring

**Goal:** Expose the distillation loop in the Commander AI Lab web UI.

- [ ] Add a "Distillation" tab or section in `ui/ai-lab.js` showing:
  - Current generation number
  - Per-generation win rate trend chart
  - Data composition pie chart (% Forge vs % PPO per generation)
  - Start / stop / pause controls for the loop
- [ ] API endpoints in `routes/ml.py`:
  - `POST /api/ml/distill/start`
  - `GET /api/ml/distill/status`
  - `POST /api/ml/distill/stop`
- [ ] History of each generation's metrics stored as JSON for the trends view

**Files touched:** `routes/ml.py`, `ui/ai-lab.js`, `ui/ai-lab.css`

---

## Phase 6 — Advanced: ELO Tracking & Model Tournament

**Goal:** Quantify improvement across generations.

- [ ] Pit each generation's model against previous generations and the Forge heuristic
      in batch sims
- [ ] Compute ELO ratings per generation
- [ ] Store in `data/elo_history.json` and visualize in the UI as a line chart
- [ ] Use ELO delta as a convergence signal — stop the loop when ELO gain per generation
      drops below a threshold

**Files touched:** new `ml/eval/elo_tracker.py`, `routes/ml.py`, `ui/ai-lab.js`

---

## Priority

| Phase | Priority | Description |
|-------|----------|-------------|
| 1     | **Critical** | PPO decision export — foundation for everything |
| 2     | **Critical** | Dataset builder ingests both sources |
| 3     | **Critical** | Quality gate prevents model regression |
| 4     | High     | Automation of the full loop |
| 5     | Medium   | UI visibility and controls |
| 6     | Low      | ELO tracking and tournament system |

> **Phases 1-3** are the core — get those working and you have a functional closed loop.
> **Phase 4** automates it. **Phases 5-6** are polish and observability.
