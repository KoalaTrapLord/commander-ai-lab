import { useState, useEffect } from 'react'
import {
  Brain, Play, RotateCw, Database, Trophy, AlertCircle,
  ToggleLeft, ToggleRight, Activity, Zap, Swords
} from 'lucide-react'
import { Spinner, StatusBadge } from '../components/common'
import { trainingApi } from '../api'
import { usePolling } from '../hooks/usePolling'
import type {
  MLStatus, MLDataStatus, MLTrainStatus, PPOTrainStatus,
  TournamentStatus, TournamentResults
} from '../types'

// ── Progress Bar ──────────────────────────────────────────────
function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-text-secondary">{label}</span>
        <span className="text-text-tertiary">{value} / {max}</span>
      </div>
      <div className="w-full h-2 bg-bg-tertiary rounded-full overflow-hidden">
        <div className="h-full bg-accent-blue rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ── Main Training Page ────────────────────────────────────────
export function TrainingPage() {
  const [mlStatus, setMlStatus] = useState<MLStatus | null>(null)
  const [dataStatus, setDataStatus] = useState<MLDataStatus | null>(null)
  const [trainStatus, setTrainStatus] = useState<MLTrainStatus | null>(null)
  const [ppoStatus, setPpoStatus] = useState<PPOTrainStatus | null>(null)
  const [tournStatus, setTournStatus] = useState<TournamentStatus | null>(null)
  const [tournResults, setTournResults] = useState<TournamentResults | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Training config
  const [epochs, setEpochs] = useState(100)
  const [lr, setLr] = useState(0.001)
  const [ppoIterations, setPpoIterations] = useState(50)
  const [tournGames, setTournGames] = useState(100)

  // Action states
  const [startingTrain, setStartingTrain] = useState(false)
  const [startingPpo, setStartingPpo] = useState(false)
  const [startingTourn, setStartingTourn] = useState(false)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const [ml, data] = await Promise.all([
          trainingApi.getMLStatus(),
          trainingApi.getDataStatus(),
        ])
        setMlStatus(ml)
        setDataStatus(data)
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [])

  // Poll training status
  const isTraining = trainStatus?.running || false
  const isPpo = ppoStatus?.running || false
  const isTourn = tournStatus?.running || false

  usePolling(async () => {
    try {
      const s = await trainingApi.getTrainStatus()
      setTrainStatus(s)
      if (!s.running) {
        const ml = await trainingApi.getMLStatus()
        setMlStatus(ml)
      }
    } catch { /* ignore */ }
  }, 2000, isTraining)

  usePolling(async () => {
    try {
      const s = await trainingApi.getPPOStatus()
      setPpoStatus(s)
    } catch { /* ignore */ }
  }, 2000, isPpo)

  usePolling(async () => {
    try {
      const s = await trainingApi.getTournamentStatus()
      setTournStatus(s)
      if (!s.running) {
        const r = await trainingApi.getTournamentResults()
        setTournResults(r)
      }
    } catch { /* ignore */ }
  }, 2000, isTourn)

  async function handleToggle() {
    setToggling(true)
    try {
      await trainingApi.toggleML()
      const ml = await trainingApi.getMLStatus()
      setMlStatus(ml)
    } catch { /* ignore */ }
    setToggling(false)
  }

  async function handleStartTrain() {
    setStartingTrain(true)
    setError(null)
    try {
      await trainingApi.startTraining({ epochs, lr })
      const s = await trainingApi.getTrainStatus()
      setTrainStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start training')
    }
    setStartingTrain(false)
  }

  async function handleStartPpo() {
    setStartingPpo(true)
    setError(null)
    try {
      await trainingApi.startPPOTraining({ iterations: ppoIterations })
      const s = await trainingApi.getPPOStatus()
      setPpoStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start PPO training')
    }
    setStartingPpo(false)
  }

  async function handleStartTournament() {
    setStartingTourn(true)
    setError(null)
    try {
      await trainingApi.startTournament({ games: tournGames })
      const s = await trainingApi.getTournamentStatus()
      setTournStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start tournament')
    }
    setStartingTourn(false)
  }

  async function handleReloadModel() {
    try {
      await trainingApi.reloadModel()
      const ml = await trainingApi.getMLStatus()
      setMlStatus(ml)
    } catch { /* ignore */ }
  }

  if (loading) {
    return <div className="p-6 flex items-center justify-center h-64"><Spinner size="lg" className="text-accent-blue" /></div>
  }

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
          <Brain className="w-6 h-6 text-accent-green" />
          ML Training
        </h1>
        <p className="text-sm text-text-secondary mt-0.5">Train and evaluate the decision-making model</p>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-status-error/10 border border-status-error/30 rounded-lg text-sm text-status-error">
          <AlertCircle className="w-4 h-4" />{error}
        </div>
      )}

      {/* Status bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <StatusBadge
          variant={mlStatus?.enabled ? 'success' : 'neutral'}
          label={mlStatus?.enabled ? 'ML Enabled' : 'ML Disabled'}
        />
        <StatusBadge
          variant={mlStatus?.model_loaded ? 'success' : 'warning'}
          label={mlStatus?.model_loaded ? 'Model Loaded' : 'No Model'}
        />
        <StatusBadge
          variant={dataStatus?.dataset_exists ? 'info' : 'neutral'}
          label={dataStatus?.dataset_exists ? `${dataStatus.samples} samples` : 'No Dataset'}
        />
        <span className="text-xs text-text-tertiary">{mlStatus?.decisions_count ?? 0} decision files</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* ML Toggle + Model */}
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Activity className="w-4 h-4 text-accent-blue" />
            Model Status
          </h3>
          <div className="flex items-center justify-between">
            <span className="text-sm text-text-secondary">ML Engine</span>
            <button onClick={handleToggle} disabled={toggling}
              className="flex items-center gap-2 text-sm transition-colors">
              {toggling ? <Spinner size="sm" /> : mlStatus?.enabled
                ? <ToggleRight className="w-6 h-6 text-accent-green" />
                : <ToggleLeft className="w-6 h-6 text-text-tertiary" />
              }
              <span className={mlStatus?.enabled ? 'text-accent-green' : 'text-text-tertiary'}>
                {mlStatus?.enabled ? 'On' : 'Off'}
              </span>
            </button>
          </div>
          {mlStatus?.model_path && (
            <div>
              <p className="text-xs text-text-tertiary">Model: {mlStatus.model_path}</p>
            </div>
          )}
          <button onClick={handleReloadModel}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors">
            <RotateCw className="w-3.5 h-3.5" />
            Reload Model
          </button>
          {dataStatus && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider">Dataset</h4>
              <div className="grid grid-cols-2 gap-2">
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Samples</p>
                  <p className="text-sm font-bold text-text-primary">{dataStatus.samples.toLocaleString()}</p>
                </div>
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Features</p>
                  <p className="text-sm font-bold text-text-primary">{dataStatus.features}</p>
                </div>
              </div>
              {dataStatus.last_built && (
                <p className="text-[10px] text-text-tertiary">Built: {new Date(dataStatus.last_built).toLocaleString()}</p>
              )}
            </div>
          )}
        </div>

        {/* Supervised Training */}
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Database className="w-4 h-4 text-accent-blue" />
            Supervised Training
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-text-tertiary">Epochs</label>
              <input type="number" min={1} max={1000} value={epochs} onChange={e => setEpochs(Number(e.target.value))}
                className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary">Learning Rate</label>
              <input type="number" min={0.00001} max={1} step={0.0001} value={lr} onChange={e => setLr(Number(e.target.value))}
                className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all" />
            </div>
          </div>
          {trainStatus?.running ? (
            <div className="space-y-3">
              <ProgressBar value={trainStatus.epoch} max={trainStatus.total_epochs} label="Training progress" />
              <div className="grid grid-cols-3 gap-2">
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Epoch</p>
                  <p className="text-sm font-bold text-text-primary">{trainStatus.epoch}/{trainStatus.total_epochs}</p>
                </div>
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Loss</p>
                  <p className="text-sm font-bold text-accent-amber">{trainStatus.loss?.toFixed(4) ?? '—'}</p>
                </div>
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Accuracy</p>
                  <p className="text-sm font-bold text-accent-green">{trainStatus.accuracy != null ? `${(trainStatus.accuracy * 100).toFixed(1)}%` : '—'}</p>
                </div>
              </div>
            </div>
          ) : (
            <button onClick={handleStartTrain} disabled={startingTrain}
              className="flex items-center gap-2 px-4 py-2.5 bg-accent-blue/15 text-accent-blue text-sm font-medium rounded-lg hover:bg-accent-blue/25 border border-accent-blue/30 transition-colors disabled:opacity-50">
              {startingTrain ? <Spinner size="sm" /> : <Play className="w-4 h-4" />}
              Start Training
            </button>
          )}
          {trainStatus && !trainStatus.running && trainStatus.best_accuracy != null && (
            <p className="text-xs text-text-secondary">Best accuracy: <span className="text-accent-green font-medium">{(trainStatus.best_accuracy * 100).toFixed(1)}%</span></p>
          )}
        </div>

        {/* PPO Training */}
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Zap className="w-4 h-4 text-accent-purple" />
            PPO Reinforcement Learning
          </h3>
          <div>
            <label className="text-xs text-text-tertiary">Iterations</label>
            <input type="number" min={1} max={500} value={ppoIterations} onChange={e => setPpoIterations(Number(e.target.value))}
              className="mt-1 w-32 px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all" />
          </div>
          {ppoStatus?.running ? (
            <div className="space-y-3">
              <ProgressBar value={ppoStatus.iteration} max={ppoStatus.total_iterations} label="PPO training progress" />
              <div className="grid grid-cols-2 gap-2">
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Avg Reward</p>
                  <p className="text-sm font-bold text-accent-amber">{ppoStatus.avg_reward?.toFixed(3) ?? '—'}</p>
                </div>
                <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
                  <p className="text-[10px] text-text-tertiary">Win Rate</p>
                  <p className="text-sm font-bold text-accent-green">{ppoStatus.win_rate != null ? `${(ppoStatus.win_rate * 100).toFixed(1)}%` : '—'}</p>
                </div>
              </div>
            </div>
          ) : (
            <button onClick={handleStartPpo} disabled={startingPpo}
              className="flex items-center gap-2 px-4 py-2.5 bg-accent-purple/15 text-accent-purple text-sm font-medium rounded-lg hover:bg-accent-purple/25 border border-accent-purple/30 transition-colors disabled:opacity-50">
              {startingPpo ? <Spinner size="sm" /> : <Play className="w-4 h-4" />}
              Start PPO Training
            </button>
          )}
        </div>

        {/* Tournament */}
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Swords className="w-4 h-4 text-accent-amber" />
            Tournament Evaluation
          </h3>
          <div>
            <label className="text-xs text-text-tertiary">Games per matchup</label>
            <input type="number" min={10} max={1000} value={tournGames} onChange={e => setTournGames(Number(e.target.value))}
              className="mt-1 w-32 px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all" />
          </div>
          {tournStatus?.running ? (
            <ProgressBar value={tournStatus.games_completed} max={tournStatus.total_games} label="Tournament progress" />
          ) : (
            <button onClick={handleStartTournament} disabled={startingTourn}
              className="flex items-center gap-2 px-4 py-2.5 bg-accent-amber/15 text-accent-amber text-sm font-medium rounded-lg hover:bg-accent-amber/25 border border-accent-amber/30 transition-colors disabled:opacity-50">
              {startingTourn ? <Spinner size="sm" /> : <Trophy className="w-4 h-4" />}
              Start Tournament
            </button>
          )}
          {tournResults && (
            <div className="mt-3">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-primary">
                    <th className="px-3 py-2 text-left text-xs text-text-tertiary font-medium">Player</th>
                    <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium">Wins</th>
                    <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium">Games</th>
                    <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium">Win Rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-primary">
                  {tournResults.players.sort((a, b) => b.win_rate - a.win_rate).map((p, i) => (
                    <tr key={p.name} className="hover:bg-bg-hover transition-colors">
                      <td className="px-3 py-2 flex items-center gap-2">
                        {i === 0 && <Trophy className="w-3 h-3 text-accent-amber" />}
                        <span className="text-text-primary">{p.name}</span>
                      </td>
                      <td className="px-3 py-2 text-right text-text-secondary">{p.wins}</td>
                      <td className="px-3 py-2 text-right text-text-secondary">{p.games}</td>
                      <td className="px-3 py-2 text-right font-semibold text-accent-blue">{(p.win_rate * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
