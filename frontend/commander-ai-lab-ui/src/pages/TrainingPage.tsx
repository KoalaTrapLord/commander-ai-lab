import { useState, useEffect, useCallback } from 'react'
import {
  Brain, Play, RotateCw, Database, Trophy, AlertCircle,
  Activity, Zap, Swords, FileText, Cpu, CheckCircle,
  ChevronDown, ChevronUp, Settings
} from 'lucide-react'
import { Spinner, StatusBadge } from '../components/common'
import { trainingApi } from '../api'
import { usePolling } from '../hooks/usePolling'
import type {
  MLStatus, MLDataStatus, MLTrainStatus, PPOTrainStatus,
  TournamentStatus, MLModelInfo
} from '../types'

// ── Progress Bar ──────────────────────────────────────────────
function ProgressBar({ value, max, label, color = 'bg-accent-blue' }: { value: number; max: number; label: string; color?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-text-secondary">{label}</span>
        <span className="text-text-tertiary">{value} / {max} ({pct.toFixed(0)}%)</span>
      </div>
      <div className="w-full h-2 bg-bg-tertiary rounded-full overflow-hidden">
        <div className={'h-full rounded-full transition-all duration-500 ' + color} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ── Phase Badge ──────────────────────────────────────────────
const PHASE_STYLES: Record<string, string> = {
  idle: 'bg-bg-tertiary text-text-tertiary',
  starting: 'bg-accent-blue/15 text-accent-blue animate-pulse',
  building: 'bg-accent-purple/15 text-accent-purple animate-pulse',
  training: 'bg-accent-blue/15 text-accent-blue animate-pulse',
  evaluating: 'bg-accent-teal/15 text-accent-teal animate-pulse',
  running: 'bg-accent-amber/15 text-accent-amber animate-pulse',
  done: 'bg-accent-green/15 text-accent-green',
  error: 'bg-accent-red/15 text-accent-red',
}

function PhaseBadge({ phase }: { phase: string }) {
  const cls = PHASE_STYLES[phase] || PHASE_STYLES.idle
  return (
    <span className={'text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded ' + cls}>
      {phase}
    </span>
  )
}

// ── Metric Card ──────────────────────────────────────────────
function MetricCard({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="px-3 py-2 bg-bg-tertiary rounded-lg">
      <p className="text-[10px] text-text-tertiary">{label}</p>
      <p className={'text-sm font-bold ' + (accent || 'text-text-primary')}>{value}</p>
    </div>
  )
}

// ── Collapsible Section ─────────────────────────────────────
function Section({ title, icon, children, defaultOpen = true, color = 'text-accent-blue' }: {
  title: string; icon: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean; color?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-bg-secondary rounded-xl border border-border-primary overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-bg-hover transition-colors"
      >
        <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
          <span className={color}>{icon}</span>
          {title}
        </h3>
        {open ? <ChevronUp className="w-4 h-4 text-text-tertiary" /> : <ChevronDown className="w-4 h-4 text-text-tertiary" />}
      </button>
      {open && <div className="px-5 pb-5 space-y-4 border-t border-border-primary pt-4">{children}</div>}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════
// Main Training Page
// ══════════════════════════════════════════════════════════════
export function TrainingPage() {
  // Status states
  const [mlStatus, setMlStatus] = useState<MLStatus | null>(null)
  const [dataStatus, setDataStatus] = useState<MLDataStatus | null>(null)
  const [modelInfo, setModelInfo] = useState<MLModelInfo | null>(null)
  const [trainStatus, setTrainStatus] = useState<MLTrainStatus | null>(null)
  const [ppoStatus, setPpoStatus] = useState<PPOTrainStatus | null>(null)
  const [tournStatus, setTournStatus] = useState<TournamentStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Supervised training config
  const [epochs, setEpochs] = useState(50)
  const [lr, setLr] = useState(0.001)
  const [batchSize, setBatchSize] = useState(256)
  const [patience, setPatience] = useState(10)
  const [rebuildDataset, setRebuildDataset] = useState(true)

  // PPO config
  const [ppoIterations, setPpoIterations] = useState(100)
  const [ppoEpisodes, setPpoEpisodes] = useState(64)
  const [ppoEpochs, setPpoEpochs] = useState(4)
  const [ppoBatchSize, setPpoBatchSize] = useState(256)
  const [ppoLr, setPpoLr] = useState(0.0003)
  const [ppoClipEps, setPpoClipEps] = useState(0.2)
  const [ppoEntropy, setPpoEntropy] = useState(0.01)
  const [ppoOpponent, setPpoOpponent] = useState('heuristic')
  const [ppoPlaystyle, _setPpoPlaystyle] = useState('midrange') // eslint-disable-line

  // Tournament config
  const [tournEpisodes, setTournEpisodes] = useState(50)
  const [tournPlaystyle, setTournPlaystyle] = useState('midrange')

  // Action states
  const [startingTrain, setStartingTrain] = useState(false)
  const [startingPpo, setStartingPpo] = useState(false)
  const [startingTourn, setStartingTourn] = useState(false)
  const [reloading, setReloading] = useState(false)
  const [showSupAdvanced, setShowSupAdvanced] = useState(false)
  const [showPpoAdvanced, setShowPpoAdvanced] = useState(false)

  // ── Initial Load ──────────────────────────────────────────
  const loadAll = useCallback(async () => {
    try {
      const [ml, data, model, train, ppo, tourn] = await Promise.all([
        trainingApi.getMLStatus().catch(() => null),
        trainingApi.getDataStatus().catch(() => null),
        trainingApi.getModelInfo().catch(() => null),
        trainingApi.getTrainStatus().catch(() => null),
        trainingApi.getPPOStatus().catch(() => null),
        trainingApi.getTournamentStatus().catch(() => null),
      ])
      if (ml) setMlStatus(ml)
      if (data) setDataStatus(data)
      if (model) setModelInfo(model)
      if (train) setTrainStatus(train)
      if (ppo) setPpoStatus(ppo)
      if (tourn) setTournStatus(tourn)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  // ── Polling ───────────────────────────────────────────────
  const isTraining = trainStatus?.running || false
  const isPpo = ppoStatus?.running || false
  const isTourn = tournStatus?.running || false
  const anyRunning = isTraining || isPpo || isTourn

  usePolling(async () => {
    try {
      const s = await trainingApi.getTrainStatus()
      setTrainStatus(s)
      if (!s.running && s.phase === 'done') {
        // Refresh model info + data when training completes
        const [model, data] = await Promise.all([
          trainingApi.getModelInfo().catch(() => null),
          trainingApi.getDataStatus().catch(() => null),
        ])
        if (model) setModelInfo(model)
        if (data) setDataStatus(data)
      }
    } catch { /* ignore */ }
  }, 2000, isTraining)

  usePolling(async () => {
    try {
      const s = await trainingApi.getPPOStatus()
      setPpoStatus(s)
      if (!s.running && s.phase === 'done') {
        const [model, data] = await Promise.all([
          trainingApi.getModelInfo().catch(() => null),
          trainingApi.getDataStatus().catch(() => null),
        ])
        if (model) setModelInfo(model)
        if (data) setDataStatus(data)
      }
    } catch { /* ignore */ }
  }, 2000, isPpo)

  usePolling(async () => {
    try {
      const s = await trainingApi.getTournamentStatus()
      setTournStatus(s)
    } catch { /* ignore */ }
  }, 2000, isTourn)

  // ── Actions ───────────────────────────────────────────────
  async function handleToggleLogging() {
    try {
      const newState = !(mlStatus?.ml_logging_enabled ?? false)
      await trainingApi.toggleML(newState)
      const ml = await trainingApi.getMLStatus()
      setMlStatus(ml)
    } catch { /* ignore */ }
  }

  async function handleReloadModel() {
    setReloading(true)
    try {
      const res = await trainingApi.reloadModel()
      setModelInfo(res.status)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reload model')
    }
    setReloading(false)
  }

  async function handleStartTrain() {
    setStartingTrain(true)
    setError(null)
    try {
      await trainingApi.startTraining({ epochs, lr, batchSize, patience, rebuildDataset })
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
      await trainingApi.startPPOTraining({
        iterations: ppoIterations,
        episodesPerIter: ppoEpisodes,
        ppoEpochs,
        batchSize: ppoBatchSize,
        lr: ppoLr,
        clipEpsilon: ppoClipEps,
        entropyCoeff: ppoEntropy,
        opponent: ppoOpponent,
        playstyle: ppoPlaystyle,
      })
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
      await trainingApi.startTournament({ episodes: tournEpisodes, playstyle: tournPlaystyle })
      const s = await trainingApi.getTournamentStatus()
      setTournStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start tournament')
    }
    setStartingTourn(false)
  }

  // ── Render ────────────────────────────────────────────────
  if (loading) {
    return <div className="p-6 flex items-center justify-center h-64"><Spinner size="lg" className="text-accent-blue" /></div>
  }

  const trainDataset = dataStatus?.datasets?.['train']
  const hasDecisions = (mlStatus?.total_decisions ?? 0) > 0
  const hasModel = modelInfo?.loaded === true

  return (
    <div className="p-6 space-y-5">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
          <Brain className="w-6 h-6 text-accent-green" />
          ML Training Pipeline
        </h1>
        <p className="text-sm text-text-secondary mt-0.5">Collect data, train models, and evaluate performance</p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-accent-red/10 border border-accent-red/30 rounded-lg text-sm text-accent-red">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-accent-red/60 hover:text-accent-red text-xs">dismiss</button>
        </div>
      )}

      {/* Pipeline overview bar */}
      <div className="flex flex-wrap items-center gap-3 bg-bg-secondary rounded-xl border border-border-primary px-5 py-3">
        <div className="flex items-center gap-2">
          <div className={'w-2 h-2 rounded-full ' + (mlStatus?.ml_logging_enabled ? 'bg-accent-green' : 'bg-text-tertiary')} />
          <span className="text-xs text-text-secondary">Logging {mlStatus?.ml_logging_enabled ? 'On' : 'Off'}</span>
        </div>
        <span className="text-border-primary">|</span>
        <span className="text-xs text-text-secondary">{mlStatus?.total_decisions ?? 0} decisions</span>
        <span className="text-border-primary">|</span>
        <span className="text-xs text-text-secondary">{trainDataset ? `${trainDataset.samples.toLocaleString()} training samples` : 'No dataset'}</span>
        <span className="text-border-primary">|</span>
        <span className="text-xs text-text-secondary">{(dataStatus?.checkpoints?.length ?? 0)} checkpoints</span>
        <span className="text-border-primary">|</span>
        <StatusBadge
          variant={hasModel ? 'success' : 'neutral'}
          label={hasModel ? `Model on ${modelInfo?.device ?? '?'}` : 'No model'}
        />
        {anyRunning && (
          <>
            <span className="text-border-primary">|</span>
            <span className="text-xs font-medium text-accent-blue animate-pulse">Pipeline running...</span>
          </>
        )}
      </div>

      {/* ═══ Phase 1: Data Collection ═══ */}
      <Section title="Phase 1 — Data Collection" icon={<FileText className="w-4 h-4" />} color="text-accent-teal">
        <div className="flex items-center justify-between">
          <p className="text-xs text-text-secondary">
            Run batch simulations with ML logging enabled to collect decision data.
          </p>
          <button
            onClick={handleToggleLogging}
            className={'flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ' +
              (mlStatus?.ml_logging_enabled
                ? 'bg-accent-green/15 text-accent-green border-accent-green/30 hover:bg-accent-green/25'
                : 'bg-bg-tertiary text-text-secondary border-border-primary hover:bg-bg-hover'
              )}
          >
            <div className={'w-2 h-2 rounded-full ' + (mlStatus?.ml_logging_enabled ? 'bg-accent-green' : 'bg-text-tertiary')} />
            {mlStatus?.ml_logging_enabled ? 'Logging Enabled' : 'Enable Logging'}
          </button>
        </div>

        {/* Decision files */}
        {(dataStatus?.decisionFiles?.length ?? 0) > 0 ? (
          <div className="space-y-1">
            <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider">Decision Files</h4>
            <div className="max-h-36 overflow-y-auto space-y-1">
              {dataStatus!.decisionFiles.map(f => (
                <div key={f.name} className="flex items-center justify-between px-3 py-1.5 bg-bg-tertiary rounded-lg text-xs">
                  <span className="text-text-secondary font-mono truncate">{f.name}</span>
                  <div className="flex items-center gap-3 text-text-tertiary">
                    <span>{f.decisions.toLocaleString()} decisions</span>
                    <span>{(f.size / 1024).toFixed(0)} KB</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="text-xs text-text-tertiary italic">No decision files yet. Run batch sims with logging enabled.</div>
        )}
      </Section>

      {/* ═══ Phase 2: Dataset & Checkpoints ═══ */}
      <Section title="Phase 2 — Dataset & Model Artifacts" icon={<Database className="w-4 h-4" />} color="text-accent-purple">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Dataset splits */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider">Dataset Splits</h4>
            {Object.keys(dataStatus?.datasets ?? {}).length > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                {(['train', 'val', 'test'] as const).map(split => {
                  const ds = dataStatus?.datasets?.[split]
                  return (
                    <div key={split} className="px-3 py-2 bg-bg-tertiary rounded-lg">
                      <p className="text-[10px] text-text-tertiary uppercase">{split}</p>
                      {ds ? (
                        <>
                          <p className="text-sm font-bold text-text-primary">{ds.samples.toLocaleString()}</p>
                          <p className="text-[10px] text-text-tertiary">{ds.features} features</p>
                        </>
                      ) : (
                        <p className="text-xs text-text-tertiary italic">Not built</p>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="text-xs text-text-tertiary italic">No dataset built yet. Training will build it automatically.</p>
            )}
          </div>

          {/* Checkpoints */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider">Checkpoints</h4>
            {(dataStatus?.checkpoints?.length ?? 0) > 0 ? (
              <div className="max-h-28 overflow-y-auto space-y-1">
                {dataStatus!.checkpoints.map(ckpt => (
                  <div key={ckpt.name} className="flex items-center justify-between px-3 py-1.5 bg-bg-tertiary rounded-lg text-xs">
                    <span className="text-text-secondary font-mono truncate">{ckpt.name}</span>
                    <span className="text-text-tertiary">{(ckpt.size / 1024 / 1024).toFixed(1)} MB</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-tertiary italic">No checkpoints yet. Train a model to generate them.</p>
            )}
          </div>
        </div>

        {/* Model info + reload */}
        <div className="flex items-center justify-between pt-2 border-t border-border-primary">
          <div className="flex items-center gap-3">
            <Cpu className="w-4 h-4 text-text-tertiary" />
            <div className="text-xs">
              {hasModel ? (
                <span className="text-accent-green font-medium">
                  Model loaded on {modelInfo?.device} | {modelInfo?.input_dim} features | {modelInfo?.num_actions} actions
                </span>
              ) : (
                <span className="text-text-tertiary">No model loaded{modelInfo?.error ? ` — ${modelInfo.error}` : ''}</span>
              )}
            </div>
          </div>
          <button
            onClick={handleReloadModel}
            disabled={reloading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors disabled:opacity-50"
          >
            {reloading ? <Spinner size="sm" /> : <RotateCw className="w-3 h-3" />}
            Reload Model
          </button>
        </div>

        {/* Eval results */}
        {dataStatus?.evalResults && (
          <div className="pt-2 border-t border-border-primary space-y-2">
            <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider flex items-center gap-2">
              <CheckCircle className="w-3.5 h-3.5 text-accent-green" />
              Latest Evaluation
            </h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {Object.entries(dataStatus.evalResults).map(([k, v]) => (
                <MetricCard
                  key={k}
                  label={k.replace(/_/g, ' ')}
                  value={typeof v === 'number' ? (k.includes('accuracy') || k.includes('rate') ? `${(v * 100).toFixed(1)}%` : v.toFixed(4)) : String(v)}
                  accent={k.includes('accuracy') ? 'text-accent-green' : undefined}
                />
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* ═══ Phase 3: Supervised Training ═══ */}
      <Section title="Phase 3 — Supervised Training" icon={<Activity className="w-4 h-4" />}>
        {/* Config */}
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Epochs</label>
              <input type="number" min={1} max={1000} value={epochs} onChange={e => setEpochs(Number(e.target.value))}
                disabled={isTraining}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Learning Rate</label>
              <input type="number" min={0.00001} max={1} step={0.0001} value={lr} onChange={e => setLr(Number(e.target.value))}
                disabled={isTraining}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
          </div>

          {/* Advanced toggle */}
          <button onClick={() => setShowSupAdvanced(!showSupAdvanced)} className="flex items-center gap-1 text-xs text-text-tertiary hover:text-text-secondary transition-colors">
            <Settings className="w-3 h-3" />
            {showSupAdvanced ? 'Hide' : 'Show'} advanced options
          </button>
          {showSupAdvanced && (
            <div className="grid grid-cols-3 gap-3 animate-fade-in">
              <div>
                <label className="text-xs text-text-tertiary block mb-1">Batch Size</label>
                <input type="number" min={16} max={2048} value={batchSize} onChange={e => setBatchSize(Number(e.target.value))}
                  disabled={isTraining}
                  className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
              </div>
              <div>
                <label className="text-xs text-text-tertiary block mb-1">Early Stop Patience</label>
                <input type="number" min={1} max={100} value={patience} onChange={e => setPatience(Number(e.target.value))}
                  disabled={isTraining}
                  className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
              </div>
              <div className="flex items-end pb-1">
                <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
                  <input type="checkbox" checked={rebuildDataset} onChange={e => setRebuildDataset(e.target.checked)}
                    disabled={isTraining}
                    className="rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30 w-3.5 h-3.5" />
                  Rebuild dataset
                </label>
              </div>
            </div>
          )}
        </div>

        {/* Training status / start button */}
        {isTraining || (trainStatus?.phase && trainStatus.phase !== 'idle') ? (
          <div className="space-y-3 bg-bg-tertiary/50 rounded-xl p-4 border border-border-primary">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <PhaseBadge phase={trainStatus!.phase} />
                <span className="text-xs text-text-secondary">{trainStatus!.message}</span>
              </div>
              {trainStatus!.started_at && (
                <span className="text-[10px] text-text-tertiary">Started: {new Date(trainStatus!.started_at).toLocaleTimeString()}</span>
              )}
            </div>

            {/* Progress bar — only in training phase */}
            {(trainStatus!.phase === 'training' || trainStatus!.phase === 'done') && trainStatus!.total_epochs > 0 && (
              <ProgressBar
                value={trainStatus!.current_epoch}
                max={trainStatus!.total_epochs}
                label="Epoch progress"
              />
            )}

            {/* Live metrics during training */}
            {trainStatus!.metrics && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(trainStatus!.metrics).map(([k, v]) => {
                  if (typeof v !== 'number') return null
                  const isAcc = k.includes('accuracy') || k.includes('acc')
                  const isLoss = k.includes('loss')
                  return (
                    <MetricCard
                      key={k}
                      label={k.replace(/_/g, ' ')}
                      value={isAcc ? `${(v * 100).toFixed(1)}%` : v.toFixed(4)}
                      accent={isAcc ? 'text-accent-green' : isLoss ? 'text-accent-amber' : undefined}
                    />
                  )
                })}
              </div>
            )}

            {/* Final result */}
            {trainStatus!.phase === 'done' && trainStatus!.result && (
              <div className="pt-2 border-t border-border-primary space-y-2">
                <h4 className="text-xs font-semibold text-accent-green flex items-center gap-1.5">
                  <CheckCircle className="w-3.5 h-3.5" /> Training Complete
                </h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <MetricCard label="Device" value={trainStatus!.result.device} />
                  <MetricCard label="Checkpoint" value={trainStatus!.result.checkpoint.split('/').pop() || '—'} />
                  {trainStatus!.result.evaluation && Object.entries(trainStatus!.result.evaluation).map(([k, v]) => (
                    typeof v === 'number' ? (
                      <MetricCard key={k} label={k.replace(/_/g, ' ')}
                        value={k.includes('accuracy') ? `${(v * 100).toFixed(1)}%` : v.toFixed(4)}
                        accent={k.includes('accuracy') ? 'text-accent-green' : undefined} />
                    ) : null
                  ))}
                </div>
              </div>
            )}

            {/* Error state */}
            {trainStatus!.phase === 'error' && trainStatus!.error && (
              <div className="flex items-start gap-2 bg-accent-red/10 border border-accent-red/20 rounded-lg px-3 py-2">
                <AlertCircle className="w-4 h-4 text-accent-red mt-0.5 flex-shrink-0" />
                <span className="text-xs text-accent-red">{trainStatus!.error}</span>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={handleStartTrain}
              disabled={startingTrain || !hasDecisions || isPpo}
              className="flex items-center gap-2 px-4 py-2.5 bg-accent-blue/15 text-accent-blue text-sm font-medium rounded-lg hover:bg-accent-blue/25 border border-accent-blue/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {startingTrain ? <Spinner size="sm" /> : <Play className="w-4 h-4" />}
              Start Training
            </button>
            {!hasDecisions && (
              <span className="text-xs text-text-tertiary italic">Enable logging and run batch sims first to generate decision data.</span>
            )}
          </div>
        )}
      </Section>

      {/* ═══ Phase 4: PPO Reinforcement Learning ═══ */}
      <Section title="Phase 4 — PPO Reinforcement Learning" icon={<Zap className="w-4 h-4" />} color="text-accent-purple" defaultOpen={false}>
        <p className="text-xs text-text-secondary">
          Fine-tune the supervised model using PPO self-play against an opponent policy.
        </p>

        {/* Config */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-text-tertiary block mb-1">Iterations</label>
            <input type="number" min={1} max={1000} value={ppoIterations} onChange={e => setPpoIterations(Number(e.target.value))}
              disabled={isPpo}
              className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
          </div>
          <div>
            <label className="text-xs text-text-tertiary block mb-1">Opponent</label>
            <select value={ppoOpponent} onChange={e => setPpoOpponent(e.target.value)}
              disabled={isPpo}
              className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50">
              <option value="heuristic">Heuristic</option>
              <option value="random">Random</option>
              <option value="self">Self-Play</option>
            </select>
          </div>
        </div>

        <button onClick={() => setShowPpoAdvanced(!showPpoAdvanced)} className="flex items-center gap-1 text-xs text-text-tertiary hover:text-text-secondary transition-colors">
          <Settings className="w-3 h-3" />
          {showPpoAdvanced ? 'Hide' : 'Show'} advanced options
        </button>
        {showPpoAdvanced && (
          <div className="grid grid-cols-3 gap-3 animate-fade-in">
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Episodes / Iter</label>
              <input type="number" min={1} max={512} value={ppoEpisodes} onChange={e => setPpoEpisodes(Number(e.target.value))}
                disabled={isPpo}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary block mb-1">PPO Epochs</label>
              <input type="number" min={1} max={20} value={ppoEpochs} onChange={e => setPpoEpochs(Number(e.target.value))}
                disabled={isPpo}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Batch Size</label>
              <input type="number" min={16} max={2048} value={ppoBatchSize} onChange={e => setPpoBatchSize(Number(e.target.value))}
                disabled={isPpo}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Learning Rate</label>
              <input type="number" min={0.000001} max={0.01} step={0.0001} value={ppoLr} onChange={e => setPpoLr(Number(e.target.value))}
                disabled={isPpo}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Clip Epsilon</label>
              <input type="number" min={0.05} max={0.5} step={0.05} value={ppoClipEps} onChange={e => setPpoClipEps(Number(e.target.value))}
                disabled={isPpo}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
            <div>
              <label className="text-xs text-text-tertiary block mb-1">Entropy Coeff</label>
              <input type="number" min={0} max={0.1} step={0.005} value={ppoEntropy} onChange={e => setPpoEntropy(Number(e.target.value))}
                disabled={isPpo}
                className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
            </div>
          </div>
        )}

        {/* PPO running status */}
        {isPpo || (ppoStatus?.phase && ppoStatus.phase !== 'idle') ? (
          <div className="space-y-3 bg-bg-tertiary/50 rounded-xl p-4 border border-border-primary">
            <div className="flex items-center gap-2">
              <PhaseBadge phase={ppoStatus!.phase} />
              <span className="text-xs text-text-secondary">{ppoStatus!.message}</span>
            </div>

            {(ppoStatus!.phase === 'training' || ppoStatus!.phase === 'done') && ppoStatus!.total_iterations > 0 && (
              <ProgressBar
                value={ppoStatus!.iteration}
                max={ppoStatus!.total_iterations}
                label="PPO iteration"
                color="bg-accent-purple"
              />
            )}

            {ppoStatus!.metrics && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {ppoStatus!.metrics.win_rate != null && (
                  <MetricCard label="Win Rate" value={`${(ppoStatus!.metrics.win_rate * 100).toFixed(1)}%`} accent="text-accent-green" />
                )}
                {ppoStatus!.metrics.avg_reward != null && (
                  <MetricCard label="Avg Reward" value={ppoStatus!.metrics.avg_reward.toFixed(3)} accent="text-accent-amber" />
                )}
                {ppoStatus!.metrics.policy_loss != null && (
                  <MetricCard label="Policy Loss" value={ppoStatus!.metrics.policy_loss.toFixed(4)} />
                )}
                {ppoStatus!.metrics.entropy != null && (
                  <MetricCard label="Entropy" value={ppoStatus!.metrics.entropy.toFixed(4)} />
                )}
              </div>
            )}

            {ppoStatus!.phase === 'done' && ppoStatus!.result && (
              <div className="flex items-center gap-2 pt-2 border-t border-border-primary">
                <CheckCircle className="w-3.5 h-3.5 text-accent-green" />
                <span className="text-xs text-accent-green font-medium">
                  PPO Training Complete — Best Win Rate: {
                    typeof ppoStatus!.result.best_win_rate === 'number'
                      ? `${(ppoStatus!.result.best_win_rate as number * 100).toFixed(1)}%`
                      : '—'
                  }
                </span>
              </div>
            )}

            {ppoStatus!.phase === 'error' && ppoStatus!.error && (
              <div className="flex items-start gap-2 bg-accent-red/10 border border-accent-red/20 rounded-lg px-3 py-2">
                <AlertCircle className="w-4 h-4 text-accent-red mt-0.5 flex-shrink-0" />
                <span className="text-xs text-accent-red">{ppoStatus!.error}</span>
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={handleStartPpo}
            disabled={startingPpo || isTraining || !hasModel}
            className="flex items-center gap-2 px-4 py-2.5 bg-accent-purple/15 text-accent-purple text-sm font-medium rounded-lg hover:bg-accent-purple/25 border border-accent-purple/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {startingPpo ? <Spinner size="sm" /> : <Play className="w-4 h-4" />}
            Start PPO Training
          </button>
        )}
        {!hasModel && !(isPpo || (ppoStatus?.phase && ppoStatus.phase !== 'idle')) && (
          <p className="text-xs text-text-tertiary italic">Train a supervised model first (Phase 3) before running PPO.</p>
        )}
      </Section>

      {/* ═══ Phase 5: Tournament Evaluation ═══ */}
      <Section title="Phase 5 — Tournament Evaluation" icon={<Swords className="w-4 h-4" />} color="text-accent-amber" defaultOpen={false}>
        <p className="text-xs text-text-secondary">
          Pit the trained model against heuristic, random, and other policy variants.
        </p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-text-tertiary block mb-1">Episodes per Matchup</label>
            <input type="number" min={10} max={1000} value={tournEpisodes} onChange={e => setTournEpisodes(Number(e.target.value))}
              disabled={isTourn}
              className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50" />
          </div>
          <div>
            <label className="text-xs text-text-tertiary block mb-1">Playstyle</label>
            <select value={tournPlaystyle} onChange={e => setTournPlaystyle(e.target.value)}
              disabled={isTourn}
              className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all disabled:opacity-50">
              <option value="midrange">Midrange</option>
              <option value="aggro">Aggro</option>
              <option value="control">Control</option>
              <option value="combo">Combo</option>
            </select>
          </div>
        </div>

        {/* Tournament status */}
        {isTourn || (tournStatus?.phase && tournStatus.phase !== 'idle') ? (
          <div className="space-y-3 bg-bg-tertiary/50 rounded-xl p-4 border border-border-primary">
            <div className="flex items-center gap-2">
              <PhaseBadge phase={tournStatus!.phase} />
              <span className="text-xs text-text-secondary">{tournStatus!.message}</span>
            </div>

            {tournStatus!.phase === 'error' && tournStatus!.error && (
              <div className="flex items-start gap-2 bg-accent-red/10 border border-accent-red/20 rounded-lg px-3 py-2">
                <AlertCircle className="w-4 h-4 text-accent-red mt-0.5 flex-shrink-0" />
                <span className="text-xs text-accent-red">{tournStatus!.error}</span>
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={handleStartTournament}
            disabled={startingTourn || isTraining || isPpo}
            className="flex items-center gap-2 px-4 py-2.5 bg-accent-amber/15 text-accent-amber text-sm font-medium rounded-lg hover:bg-accent-amber/25 border border-accent-amber/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {startingTourn ? <Spinner size="sm" /> : <Trophy className="w-4 h-4" />}
            Start Tournament
          </button>
        )}

        {/* Tournament results */}
        {(tournStatus?.result?.players?.length ?? 0) > 0 && (
          <div className="pt-2 border-t border-border-primary space-y-2">
            <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider flex items-center gap-2">
              <Trophy className="w-3.5 h-3.5 text-accent-amber" />
              Leaderboard
            </h4>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-primary">
                  <th className="px-3 py-2 text-left text-xs text-text-tertiary font-medium w-8">#</th>
                  <th className="px-3 py-2 text-left text-xs text-text-tertiary font-medium">Policy</th>
                  <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium">Wins</th>
                  <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium">Games</th>
                  <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium">Win Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-primary">
                {tournStatus!.result!.players
                  .sort((a, b) => b.win_rate - a.win_rate)
                  .map((p, i) => (
                    <tr key={p.name} className="hover:bg-bg-hover transition-colors">
                      <td className="px-3 py-2 text-text-tertiary text-xs">
                        {i === 0 ? <Trophy className="w-3.5 h-3.5 text-accent-amber" /> : i + 1}
                      </td>
                      <td className="px-3 py-2">
                        <span className="text-text-primary font-medium capitalize">{p.name}</span>
                      </td>
                      <td className="px-3 py-2 text-right text-text-secondary">{p.wins}</td>
                      <td className="px-3 py-2 text-right text-text-secondary">{p.games}</td>
                      <td className={'px-3 py-2 text-right font-semibold ' + (i === 0 ? 'text-accent-green' : 'text-accent-blue')}>
                        {(p.win_rate * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  )
}
