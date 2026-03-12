import { useState, useEffect } from 'react'
import {
  Gamepad2, Play, Wifi, WifiOff, Settings,
  AlertCircle, Trophy, Clock, Brain
} from 'lucide-react'
import { Spinner, StatusBadge } from '../components/common'
import { simApi, labApi } from '../api'
import { usePolling } from '../hooks/usePolling'
import type { SimStatus, SimResult, DeepSeekStatus, LabDeck } from '../types'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export function SimulatorPage() {
  const [decks, setDecks] = useState<LabDeck[]>([])
  const [deckA, setDeckA] = useState('')
  const [deckB, setDeckB] = useState('')
  const [games, setGames] = useState(50)
  const [useDeepSeek, setUseDeepSeek] = useState(false)
  const [deepSeekDeck, setDeepSeekDeck] = useState('')
  const [dsStatus, setDsStatus] = useState<DeepSeekStatus | null>(null)
  const [running, setRunning] = useState(false)
  const [simId, setSimId] = useState<string | null>(null)
  const [simStatus, setSimStatus] = useState<SimStatus | null>(null)
  const [result, setResult] = useState<SimResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  // DS config
  const [showDsConfig, setShowDsConfig] = useState(false)
  const [dsModel, setDsModel] = useState('')
  const [dsUrl, setDsUrl] = useState('')

  useEffect(() => {
    labApi.getLabDecks().then(setDecks).catch(() => {})
    simApi.getDeepSeekStatus().then(s => {
      setDsStatus(s)
      if (s.model) setDsModel(s.model)
      if (s.base_url) setDsUrl(s.base_url)
    }).catch(() => {})
  }, [])

  // Poll while running
  usePolling(async () => {
    if (!simId) return
    try {
      const s = await simApi.getSimStatus(simId)
      setSimStatus(s)
      if (!s.running) {
        const r = await simApi.getSimResult(simId)
        setResult(r)
        setRunning(false)
      }
    } catch { /* ignore */ }
  }, 2000, running)

  async function handleStart() {
    if (!deckA || !deckB) { setError('Select both decks'); return }
    setStarting(true)
    setError(null)
    setResult(null)
    try {
      let res
      if (useDeepSeek && deepSeekDeck) {
        res = await simApi.runDeepSeekSim({ deck_a: deckA, deck_b: deckB, games, deepseek_deck: deepSeekDeck })
      } else {
        res = await simApi.runSim({ deck_a: deckA, deck_b: deckB, games })
      }
      setSimId(res.sim_id)
      setRunning(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    }
    setStarting(false)
  }

  async function handleDsConnect() {
    try {
      const s = await simApi.connectDeepSeek()
      setDsStatus(s)
    } catch { /* ignore */ }
  }

  async function handleDsConfigure() {
    try {
      const s = await simApi.configureDeepSeek({
        model: dsModel || undefined,
        base_url: dsUrl || undefined,
      })
      setDsStatus(s)
      setShowDsConfig(false)
    } catch { /* ignore */ }
  }

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
          <Gamepad2 className="w-6 h-6 text-accent-purple" />
          Simulator
        </h1>
        <p className="text-sm text-text-secondary mt-0.5">Run head-to-head deck simulations</p>
      </div>

      {/* DeepSeek status */}
      <div className="flex items-center gap-3">
        <StatusBadge
          variant={dsStatus?.connected ? 'success' : 'warning'}
          label={dsStatus?.connected ? `DeepSeek: ${dsStatus.model}` : 'DeepSeek: Disconnected'}
        />
        <button onClick={handleDsConnect}
          className="flex items-center gap-1.5 text-xs text-text-tertiary hover:text-text-secondary transition-colors">
          {dsStatus?.connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
          {dsStatus?.connected ? 'Reconnect' : 'Connect'}
        </button>
        <button onClick={() => setShowDsConfig(!showDsConfig)}
          className="flex items-center gap-1.5 text-xs text-text-tertiary hover:text-text-secondary transition-colors">
          <Settings className="w-3 h-3" />
          Configure
        </button>
      </div>

      {showDsConfig && (
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-4 max-w-md animate-fade-in space-y-3">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Brain className="w-4 h-4 text-accent-purple" />
            DeepSeek Configuration
          </h3>
          <input
            type="text"
            placeholder="Model name"
            value={dsModel}
            onChange={e => setDsModel(e.target.value)}
            className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
          />
          <input
            type="text"
            placeholder="Base URL (e.g. http://192.168.0.122:1234)"
            value={dsUrl}
            onChange={e => setDsUrl(e.target.value)}
            className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
          />
          <button onClick={handleDsConfigure}
            className="px-4 py-2 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors">
            Save
          </button>
        </div>
      )}

      {/* Sim config */}
      <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4 max-w-2xl">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-text-tertiary uppercase tracking-wider">Deck A</label>
            <select
              value={deckA}
              onChange={e => setDeckA(e.target.value)}
              className="mt-1 w-full px-3 py-2.5 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all"
            >
              <option value="">Select deck...</option>
              {decks.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-text-tertiary uppercase tracking-wider">Deck B</label>
            <select
              value={deckB}
              onChange={e => setDeckB(e.target.value)}
              className="mt-1 w-full px-3 py-2.5 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all"
            >
              <option value="">Select deck...</option>
              {decks.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div>
            <label className="text-xs text-text-tertiary uppercase tracking-wider">Games</label>
            <input
              type="number" min={1} max={1000}
              value={games}
              onChange={e => setGames(Number(e.target.value))}
              className="mt-1 w-24 px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all"
            />
          </div>
          <label className="flex items-center gap-2 cursor-pointer mt-5">
            <input type="checkbox" checked={useDeepSeek} onChange={e => setUseDeepSeek(e.target.checked)}
              className="w-4 h-4 rounded border-border-primary bg-bg-tertiary text-accent-purple focus:ring-accent-purple/30" />
            <span className="text-sm text-text-secondary">Use DeepSeek AI pilot</span>
          </label>
          {useDeepSeek && (
            <div className="mt-5">
              <select
                value={deepSeekDeck}
                onChange={e => setDeepSeekDeck(e.target.value)}
                className="px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all"
              >
                <option value="">AI pilots which deck?</option>
                {[deckA, deckB].filter(Boolean).map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
          )}
        </div>

        {error && (
          <div className="flex items-center gap-2 px-4 py-2 bg-status-error/10 border border-status-error/30 rounded-lg text-sm text-status-error">
            <AlertCircle className="w-4 h-4" />{error}
          </div>
        )}

        {running ? (
          <div className="flex items-center gap-3">
            <Spinner size="md" className="text-accent-blue" />
            <div>
              <p className="text-sm text-text-primary">Simulation running...</p>
              {simStatus && (
                <p className="text-xs text-text-tertiary">
                  {simStatus.games_completed ?? 0} / {simStatus.total_games ?? games} games
                </p>
              )}
            </div>
          </div>
        ) : (
          <button onClick={handleStart} disabled={starting || !deckA || !deckB}
            className="flex items-center gap-2 px-5 py-2.5 bg-accent-purple/15 text-accent-purple text-sm font-semibold rounded-lg hover:bg-accent-purple/25 border border-accent-purple/30 transition-colors disabled:opacity-50">
            {starting ? <Spinner size="sm" /> : <Play className="w-4 h-4" />}
            Run Simulation
          </button>
        )}
      </div>

      {/* Results */}
      {result && (
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4 animate-fade-in">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Trophy className="w-4 h-4 text-accent-amber" />
              Results
            </h3>
            <span className="text-xs text-text-tertiary flex items-center gap-1.5">
              <Clock className="w-3 h-3" />
              {(result.duration_ms / 1000).toFixed(1)}s · {result.total_games} games
            </span>
          </div>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={result.decks.map(d => ({ name: d.name, win_rate: Math.round(d.win_rate * 100) }))} barSize={40}>
                <XAxis dataKey="name" tick={{ fill: '#9ba1b8', fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} tick={{ fill: '#6b7190', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#1c2030', border: '1px solid #2a2f42', borderRadius: 8, fontSize: 12 }}
                  formatter={(value: unknown) => [`${value}%`, 'Win Rate']} />
                <Bar dataKey="win_rate" radius={[4, 4, 0, 0]}>
                  {result.decks.map((d, i) => (
                    <Cell key={i} fill={d.win_rate === Math.max(...result.decks.map(x => x.win_rate)) ? '#4ade80' : '#4f6ef7'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {result.decks.map(d => (
              <div key={d.name} className="px-4 py-3 rounded-lg bg-bg-tertiary">
                <p className="text-sm font-semibold text-text-primary">{d.name}</p>
                <div className="grid grid-cols-3 gap-2 mt-2">
                  <div>
                    <p className="text-[10px] text-text-tertiary uppercase">Wins</p>
                    <p className="text-lg font-bold text-accent-green">{d.wins}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-tertiary uppercase">Win Rate</p>
                    <p className="text-lg font-bold text-accent-blue">{(d.win_rate * 100).toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-tertiary uppercase">Avg Turn</p>
                    <p className="text-lg font-bold text-text-primary">{d.avg_turn.toFixed(1)}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
