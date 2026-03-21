# Phase 1 — Self-Play Integration Checklist

> **Issue:** #65 — PPO Decision Exporter  
> **Ref:** `docs/CLOSED-LOOP-DISTILLATION.md`  
> **Status:** In Progress

---

## Completed

- [x] Create `ml/training/decision_exporter.py` with `DecisionExporter` class
- [x] `ExporterConfig` dataclass (output_dir, only_wins, model_version, min_episode_steps)
- [x] `build_decision_record()` — converts PPO step data into Forge-compatible JSONL format
- [x] `DecisionExporter.begin_episode()` / `record_step()` / `end_episode()` / `flush()` lifecycle
- [x] Write to `data/results/ml-decisions-ppo-{batch_id}.jsonl`
- [x] Include PPO metadata fields: `source`, `model_version`, `reward`, `episode_return`
- [x] Win-only filtering (only export decisions from winning games)
- [x] Short-episode gating (`min_episode_steps` threshold)
- [x] `_macro_action_to_forge_type()` mapping (MacroAction enum → Forge action type strings)
- [x] Export stats tracking (`stats` property)

---

## Remaining — Integrate into `ml/training/self_play.py`

### Import

- [ ] Add import: `from ml.training.decision_exporter import DecisionExporter`

### Modify `run_self_play_episode()` 

- [ ] Add `exporter: DecisionExporter = None` parameter to function signature
- [ ] After each `trajectory.append(...)` block (3 locations), add:
  ```python
  if exporter is not None:
      exporter.record_step(
          game_state_snapshot=prev_snapshot,
          action_idx=action_idx,
          reward=reward,
      )
  ```

### Modify `collect_rollouts()`

- [ ] Add `exporter: DecisionExporter = None` parameter to function signature
- [ ] Before each episode, call:
  ```python
  if exporter is not None:
      exporter.begin_episode(agent_seat=agent_seat, playstyle=playstyle)
  ```
- [ ] Pass `exporter=exporter` to `run_self_play_episode()`
- [ ] After outcome tracking, call:
  ```python
  if exporter is not None:
      won = trajectory and trajectory[-1]["done"] and trajectory[-1]["reward"] > 0.5
      ep_return = sum(s["reward"] for s in trajectory)
      exporter.end_episode(won=won, episode_return=ep_return)
  ```

### Commit

- [ ] `git add ml/training/self_play.py`
- [ ] `git commit -m "feat(ml): integrate DecisionExporter into self-play rollouts (#65)"`
- [ ] `git push origin main`

---

## Integration Pattern

```
collect_rollouts(exporter=exporter)
  └─ for each episode:
       ├─ exporter.begin_episode(seat, playstyle)
       ├─ run_self_play_episode(..., exporter=exporter)
       │    └─ for each step:
       │         ├─ trajectory.append(step_data)
       │         └─ exporter.record_step(snapshot, action, reward)
       └─ exporter.end_episode(won, episode_return)
  # Caller does: exporter.flush()
```

---

## Terminal Commands

```bash
cd commander-ai-lab
git pull origin main
# Make edits to ml/training/self_play.py per checklist above
git add ml/training/self_play.py
git commit -m "feat(ml): integrate DecisionExporter into self-play rollouts (#65)"
git push origin main
```
