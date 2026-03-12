import { useState, useEffect } from 'react'
import {
  FlaskConical, Play, Clock, Trophy,
  Upload, Link, FileText, History, ChevronRight, AlertCircle,
  Check
} from 'lucide-react'
import { Spinner } from '../components/common'
import { labApi } from '../api'
import { usePolling } from '../hooks/usePolling'
import type { LabDeck, LabStatus, LabResult, LabHistoryEntry, PreconDeck } from '../types'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

// ── Results Chart ─────────────────────────────────────────────
function ResultsChart({ result }: { result: LabResult }) {
  const data = result.decks
    .sort((a, b) => b.win_rate - a.win_rate)
    .map(d => ({
      name: d.name.length > 20 ? d.name.slice(0, 18) + '...' : d.name,
      win_rate: Math.round(d.win_rate * 100),
      fullName: d.name,
    }))

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" barSize={20} margin={{ left: 10, right: 20 }}>
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#6b7190', fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" width={150} tick={{ fill: '#9ba1b8', fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ backgroundColor: '#1c2030', border: '1px solid #2a2f42', borderRadius: 8, fontSize: 12 }}
            formatter={(value: unknown) => [`${value}%`, 'Win Rate']}
            labelFormatter={(label: unknown) => data.find(d => d.name === String(label))?.fullName || String(label)}
          />
          <Bar dataKey="win_rate" radius={[0, 4, 4, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={i === 0 ? '#4ade80' : i === 1 ? '#4f6ef7' : '#363c54'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Deck Selector ─────────────────────────────────────────────
function DeckSelector({
  decks,
  selected,
  onToggle,
  precons,
  onInstallPrecon,
}: {
  decks: LabDeck[]
  selected: Set<string>
  onToggle: (name: string) => void
  precons: PreconDeck[]
  onInstallPrecon: (name: string) => void
}) {
  const [showPrecons, setShowPrecons] = useState(false)
  const [installing, setInstalling] = useState<string | null>(null)

  async function handleInstall(name: string) {
    setInstalling(name)
    await onInstallPrecon(name)
    setInstalling(null)
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-text-primary">Available Decks</h3>
      {decks.length === 0 ? (
        <p className="text-xs text-text-tertiary">No decks available. Import or install precons.</p>
      ) : (
        <div className="space-y-1 max-h-64 overflow-y-auto">
          {decks.map(d => (
            <label key={d.name} className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-bg-hover cursor-pointer transition-colors">
              <input
                type="checkbox"
                checked={selected.has(d.name)}
                onChange={() => onToggle(d.name)}
                className="w-4 h-4 rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30"
              />
              <div className="flex-1 min-w-0">
                <span className="text-sm text-text-primary truncate block">{d.name}</span>
                <span className="text-[10px] text-text-tertiary">{d.source} · {d.card_count} cards</span>
              </div>
            </label>
          ))}
        </div>
      )}

      <button
        onClick={() => setShowPrecons(!showPrecons)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium bg-bg-tertiary rounded-lg text-text-secondary hover:bg-bg-hover border border-border-primary transition-colors"
      >
        Precon Decks
        <ChevronRight className={`w-3.5 h-3.5 transition-transform ${showPrecons ? 'rotate-90' : ''}`} />
      </button>

      {showPrecons && (
        <div className="space-y-1 max-h-48 overflow-y-auto animate-fade-in">
          {precons.map(p => (
            <div key={p.name} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-bg-tertiary">
              <span className="flex-1 text-xs text-text-secondary truncate">{p.name}</span>
              {p.installed ? (
                <span className="text-[10px] text-accent-green flex items-center gap-1"><Check className="w-3 h-3" /> Installed</span>
              ) : (
                <button
                  onClick={() => handleInstall(p.name)}
                  disabled={installing === p.name}
                  className="text-[10px] text-accent-blue hover:text-accent-blue-hover transition-colors"
                >
                  {installing === p.name ? <Spinner size="sm" /> : 'Install'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Import Panel ──────────────────────────────────────────────
function ImportPanel({ onImported }: { onImported: () => void }) {
  const [importUrl, setImportUrl] = useState('')
  const [importText, setImportText] = useState('')
  const [importName, setImportName] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMode, setImportMode] = useState<'url' | 'text'>('url')

  async function handleImport() {
    setImporting(true)
    try {
      if (importMode === 'url' && importUrl.trim()) {
        await labApi.importDeckFromUrl(importUrl.trim())
      } else if (importMode === 'text' && importText.trim()) {
        await labApi.importDeckFromText(importText.trim(), importName || undefined)
      }
      setImportUrl('')
      setImportText('')
      setImportName('')
      onImported()
    } catch { /* ignore */ }
    setImporting(false)
  }

  return (
    <div className="bg-bg-secondary rounded-xl border border-border-primary p-4 space-y-3">
      <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
        <Upload className="w-4 h-4 text-accent-blue" />
        Import Deck
      </h3>
      <div className="flex gap-1">
        <button onClick={() => setImportMode('url')}
          className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${importMode === 'url' ? 'bg-accent-blue/15 text-accent-blue' : 'bg-bg-tertiary text-text-tertiary'}`}>
          <Link className="w-3 h-3 inline mr-1" />URL
        </button>
        <button onClick={() => setImportMode('text')}
          className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${importMode === 'text' ? 'bg-accent-blue/15 text-accent-blue' : 'bg-bg-tertiary text-text-tertiary'}`}>
          <FileText className="w-3 h-3 inline mr-1" />Text
        </button>
      </div>
      {importMode === 'url' ? (
        <input
          type="text"
          placeholder="Moxfield, Archidekt, or deck URL..."
          value={importUrl}
          onChange={e => setImportUrl(e.target.value)}
          className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
        />
      ) : (
        <>
          <input
            type="text"
            placeholder="Deck name"
            value={importName}
            onChange={e => setImportName(e.target.value)}
            className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
          />
          <textarea
            placeholder={"1x Sol Ring\n1x Command Tower\n..."}
            value={importText}
            onChange={e => setImportText(e.target.value)}
            rows={5}
            className="w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary font-mono focus:outline-none focus:border-accent-blue/50 transition-all resize-none"
          />
        </>
      )}
      <button onClick={handleImport} disabled={importing}
        className="w-full px-4 py-2 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors disabled:opacity-50">
        {importing ? <Spinner size="sm" /> : 'Import'}
      </button>
    </div>
  )
}

// ── Main Batch Sim Page ───────────────────────────────────────
export function BatchSimPage() {
  const [decks, setDecks] = useState<LabDeck[]>([])
  const [precons, setPrecons] = useState<PreconDeck[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [games, setGames] = useState(100)
  const [status, setStatus] = useState<LabStatus | null>(null)
  const [result, setResult] = useState<LabResult | null>(null)
  const [history, setHistory] = useState<LabHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  async function fetchDecks() {
    try {
      const [d, p] = await Promise.all([labApi.getLabDecks(), labApi.getPrecons()])
      setDecks(d)
      setPrecons(p)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => {
    fetchDecks()
    labApi.getLabStatus().then(setStatus).catch(() => {})
    labApi.getLabHistory().then(setHistory).catch(() => {})
  }, [])

  // Poll while running
  usePolling(async () => {
    try {
      const s = await labApi.getLabStatus()
      setStatus(s)
      if (!s.running && s.run_id) {
        const r = await labApi.getLabResult()
        setResult(r)
        labApi.getLabHistory().then(setHistory).catch(() => {})
      }
    } catch { /* ignore */ }
  }, 2000, status?.running || false)

  function toggleDeck(name: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  async function handleStart() {
    if (selected.size < 2) { setError('Select at least 2 decks'); return }
    setStarting(true)
    setError(null)
    setResult(null)
    try {
      await labApi.startBatchSim({ decks: [...selected], games })
      const s = await labApi.getLabStatus()
      setStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    }
    setStarting(false)
  }

  async function handleInstallPrecon(name: string) {
    try {
      await labApi.installPrecon(name)
      fetchDecks()
    } catch { /* ignore */ }
  }

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
          <FlaskConical className="w-6 h-6 text-accent-teal" />
          Batch Simulator
        </h1>
        <p className="text-sm text-text-secondary mt-0.5">Run mass simulations between decks</p>
      </div>

      <div className="flex gap-5">
        {/* Left sidebar: deck selection + import */}
        <div className="w-72 flex-shrink-0 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center h-32"><Spinner size="md" className="text-accent-blue" /></div>
          ) : (
            <DeckSelector
              decks={decks}
              selected={selected}
              onToggle={toggleDeck}
              precons={precons}
              onInstallPrecon={handleInstallPrecon}
            />
          )}
          <ImportPanel onImported={fetchDecks} />
        </div>

        {/* Main content */}
        <div className="flex-1 space-y-5">
          {/* Config + Start */}
          <div className="bg-bg-secondary rounded-xl border border-border-primary p-5">
            <div className="flex items-center gap-4">
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Games</label>
                <input
                  type="number"
                  min={10}
                  max={10000}
                  step={10}
                  value={games}
                  onChange={e => setGames(Number(e.target.value))}
                  className="mt-1 w-28 px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all"
                />
              </div>
              <div className="flex-1">
                <p className="text-xs text-text-tertiary">Selected: {selected.size} decks</p>
              </div>
              {status?.running ? (
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Spinner size="sm" className="text-accent-blue" />
                    <span className="text-sm text-text-secondary">
                      {status.games_completed} / {status.total_games} games
                    </span>
                  </div>
                  <div className="w-48 h-2 bg-bg-tertiary rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent-blue rounded-full transition-all"
                      style={{ width: `${status.total_games ? (status.games_completed / status.total_games) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              ) : (
                <button onClick={handleStart} disabled={starting || selected.size < 2}
                  className="flex items-center gap-2 px-5 py-2.5 bg-accent-teal/15 text-accent-teal text-sm font-semibold rounded-lg hover:bg-accent-teal/25 border border-accent-teal/30 transition-colors disabled:opacity-50">
                  {starting ? <Spinner size="sm" /> : <Play className="w-4 h-4" />}
                  Start Simulation
                </button>
              )}
            </div>
            {error && (
              <div className="mt-3 flex items-center gap-2 px-4 py-2 bg-status-error/10 border border-status-error/30 rounded-lg text-sm text-status-error">
                <AlertCircle className="w-4 h-4" />{error}
              </div>
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
                <span className="text-xs text-text-tertiary">{result.total_games} games · {new Date(result.timestamp).toLocaleString()}</span>
              </div>
              <ResultsChart result={result} />
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border-primary">
                      <th className="px-3 py-2 text-left text-xs text-text-tertiary font-medium uppercase tracking-wider">Deck</th>
                      <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium uppercase tracking-wider">Wins</th>
                      <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium uppercase tracking-wider">Games</th>
                      <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium uppercase tracking-wider">Win Rate</th>
                      <th className="px-3 py-2 text-right text-xs text-text-tertiary font-medium uppercase tracking-wider">Avg Turns</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-primary">
                    {result.decks.sort((a, b) => b.win_rate - a.win_rate).map((d, i) => (
                      <tr key={d.name} className="hover:bg-bg-hover transition-colors">
                        <td className="px-3 py-2.5 flex items-center gap-2">
                          {i === 0 && <Trophy className="w-3.5 h-3.5 text-accent-amber" />}
                          <span className="font-medium text-text-primary">{d.name}</span>
                        </td>
                        <td className="px-3 py-2.5 text-right text-text-secondary">{d.wins}</td>
                        <td className="px-3 py-2.5 text-right text-text-secondary">{d.games}</td>
                        <td className="px-3 py-2.5 text-right font-semibold text-accent-blue">{(d.win_rate * 100).toFixed(1)}%</td>
                        <td className="px-3 py-2.5 text-right text-text-secondary">{d.avg_turns.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* History */}
          <div>
            <button onClick={() => setShowHistory(!showHistory)}
              className="flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary transition-colors">
              <History className="w-4 h-4" />
              Run History ({history.length})
              <ChevronRight className={`w-3.5 h-3.5 transition-transform ${showHistory ? 'rotate-90' : ''}`} />
            </button>
            {showHistory && history.length > 0 && (
              <div className="mt-3 space-y-2 animate-fade-in">
                {history.map(h => (
                  <div key={h.run_id} className="flex items-center gap-4 px-4 py-3 bg-bg-secondary rounded-lg border border-border-primary">
                    <Clock className="w-4 h-4 text-text-tertiary" />
                    <div className="flex-1">
                      <p className="text-sm text-text-primary">{h.decks.join(' vs ')}</p>
                      <p className="text-xs text-text-tertiary">{new Date(h.timestamp).toLocaleString()} · {h.total_games} games</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
