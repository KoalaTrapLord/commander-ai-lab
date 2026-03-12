import { useState, useEffect, useRef } from 'react'
import {
  Search, Wand2, Save, AlertCircle,
  ChevronDown, Sparkles, RefreshCw, Check
} from 'lucide-react'
import { Spinner, StatusBadge, ManaSymbols, CardImage, ColorDots } from '../components/common'
import { deckgenApi } from '../api'
import type { DeckGenV3Status, DeckGenV3Result, DeckGenV3Card, CommanderSearchResult } from '../types'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

// ── Commander Search ──────────────────────────────────────────
function CommanderSearch({ onSelect }: { onSelect: (c: CommanderSearchResult) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CommanderSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  function handleSearch(q: string) {
    setQuery(q)
    clearTimeout(debounceRef.current)
    if (q.length < 2) { setResults([]); return }
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const r = await deckgenApi.searchCommanders(q)
        setResults(r)
      } catch { setResults([]) }
      setSearching(false)
    }, 300)
  }

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
        <input
          type="text"
          placeholder="Search for a commander..."
          value={query}
          onChange={e => handleSearch(e.target.value)}
          className="w-full pl-10 pr-4 py-3 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 focus:ring-1 focus:ring-accent-blue/30 transition-all"
        />
        {searching && <Spinner size="sm" className="absolute right-3 top-1/2 -translate-y-1/2 text-accent-blue" />}
      </div>
      {results.length > 0 && (
        <div className="absolute z-20 top-full mt-1 w-full bg-bg-elevated border border-border-primary rounded-xl shadow-lg max-h-80 overflow-y-auto">
          {results.map(c => (
            <button
              key={c.scryfall_id}
              onClick={() => { onSelect(c); setQuery(c.name); setResults([]) }}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-bg-hover text-left transition-colors"
            >
              <CardImage src={c.image_url} alt={c.name} size="sm" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary truncate">{c.name}</p>
                <p className="text-xs text-text-secondary truncate">{c.type_line}</p>
              </div>
              <ColorDots colors={c.color_identity} />
              {c.in_collection && (
                <span className="text-[10px] px-1.5 py-0.5 bg-accent-green/15 text-accent-green rounded">Owned</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Generated Deck View ───────────────────────────────────────
function GeneratedDeckView({ result, onCommit }: { result: DeckGenV3Result; onCommit: () => void }) {
  const [view, setView] = useState<'visual' | 'list'>('visual')
  const [committing, setCommitting] = useState(false)
  const [selectedCard, setSelectedCard] = useState<DeckGenV3Card | null>(null)

  // Group by category
  const grouped = result.cards.reduce<Record<string, DeckGenV3Card[]>>((acc, c) => {
    const cat = c.category || 'Other'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(c)
    return acc
  }, {})

  const curveData = Object.entries(result.stats.mana_curve)
    .map(([cmc, count]) => ({ cmc: cmc === '7' ? '7+' : cmc, count }))
    .sort((a, b) => Number(a.cmc) - Number(b.cmc))

  async function handleCommit() {
    setCommitting(true)
    try { onCommit() } catch { /* ignore */ }
    setCommitting(false)
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Commander header */}
      <div className="flex gap-5 bg-bg-secondary rounded-xl border border-border-primary p-5">
        <CardImage src={result.commander.image_url} alt={result.commander.name} size="lg" />
        <div className="flex-1 space-y-3">
          <div>
            <h2 className="text-xl font-bold text-text-primary">{result.commander.name}</h2>
            <p className="text-sm text-text-secondary">{result.commander.type_line}</p>
            <div className="flex items-center gap-3 mt-2">
              <ManaSymbols cost={result.commander.mana_cost} size="md" />
              <ColorDots colors={result.commander.color_identity} size="md" />
            </div>
          </div>
          <p className="text-sm text-text-primary whitespace-pre-wrap">{result.commander.oracle_text}</p>
          <div className="flex items-center gap-4 text-xs text-text-secondary">
            <span>Strategy: <span className="text-accent-blue font-medium">{result.strategy}</span></span>
            <span>Bracket: <span className="text-accent-amber font-medium">{result.bracket}</span></span>
            <span>Model: <span className="text-accent-purple font-medium">{result.model}</span></span>
          </div>
          {result.substitution && (
            <div className="flex items-center gap-3 text-xs">
              <span className="text-accent-green">{result.substitution.owned} owned</span>
              <span className="text-accent-amber">{result.substitution.substituted} substituted</span>
              <span className="text-accent-red">{result.substitution.missing} missing</span>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button onClick={handleCommit} disabled={committing}
          className="flex items-center gap-2 px-4 py-2.5 bg-accent-green/15 text-accent-green text-sm font-medium rounded-lg hover:bg-accent-green/25 border border-accent-green/30 transition-colors disabled:opacity-50">
          {committing ? <Spinner size="sm" /> : <Save className="w-4 h-4" />}
          Save to Decks
        </button>
        <div className="flex items-center gap-1 bg-bg-secondary rounded-lg border border-border-primary p-0.5">
          <button onClick={() => setView('visual')}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${view === 'visual' ? 'bg-bg-hover text-text-primary' : 'text-text-tertiary hover:text-text-secondary'}`}>
            Visual
          </button>
          <button onClick={() => setView('list')}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${view === 'list' ? 'bg-bg-hover text-text-primary' : 'text-text-tertiary hover:text-text-secondary'}`}>
            List
          </button>
        </div>
        {/* Stats summary */}
        <div className="flex-1" />
        <span className="text-xs text-text-tertiary">{result.stats.card_count} cards</span>
        <span className="text-xs text-accent-teal font-medium">${result.stats.total_price.toFixed(2)}</span>
      </div>

      {/* Mana curve mini */}
      <div className="bg-bg-secondary rounded-xl border border-border-primary p-4">
        <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider mb-2">Mana Curve</h4>
        <div className="h-28">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={curveData} barSize={20}>
              <XAxis dataKey="cmc" axisLine={false} tickLine={false} tick={{ fill: '#6b7190', fontSize: 10 }} />
              <YAxis hide />
              <Tooltip contentStyle={{ backgroundColor: '#1c2030', border: '1px solid #2a2f42', borderRadius: 8, fontSize: 11 }} />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {curveData.map((_, i) => <Cell key={i} fill="#4f6ef7" fillOpacity={0.8} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Card grid/list */}
      {view === 'visual' ? (
        <div className="space-y-5">
          {Object.entries(grouped).map(([cat, cards]) => (
            <div key={cat}>
              <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider mb-3">{cat} ({cards.length})</h4>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-2">
                {cards.map(card => (
                  <div key={card.name} className="group cursor-pointer relative" onClick={() => setSelectedCard(card)}>
                    <CardImage src={card.image_url} alt={card.name} size="md" className="w-full h-auto aspect-[5/7]" />
                    {card.is_substitute && (
                      <div className="absolute top-1 right-1 w-4 h-4 bg-accent-amber rounded-full flex items-center justify-center">
                        <RefreshCw className="w-2.5 h-2.5 text-bg-primary" />
                      </div>
                    )}
                    {card.owned && (
                      <div className="absolute top-1 left-1 w-4 h-4 bg-accent-green rounded-full flex items-center justify-center">
                        <Check className="w-2.5 h-2.5 text-bg-primary" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-bg-secondary rounded-xl border border-border-primary overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-primary text-left">
                <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Card</th>
                <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Category</th>
                <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Role</th>
                <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Mana</th>
                <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider text-right">Price</th>
                <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-primary">
              {result.cards.map(card => (
                <tr key={card.name} className="hover:bg-bg-hover transition-colors">
                  <td className="px-4 py-2.5">
                    <span className="font-medium text-text-primary">{card.quantity}x {card.name}</span>
                    {card.is_substitute && (
                      <span className="ml-2 text-[10px] text-accent-amber">sub for {card.original_name}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-text-secondary">{card.category}</td>
                  <td className="px-4 py-2.5 text-xs text-text-secondary">{card.role}</td>
                  <td className="px-4 py-2.5"><ManaSymbols cost={card.mana_cost} /></td>
                  <td className="px-4 py-2.5 text-right text-accent-teal text-xs">{card.tcg_price != null ? `$${card.tcg_price.toFixed(2)}` : '—'}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-[10px] px-2 py-0.5 rounded ${card.owned ? 'bg-accent-green/15 text-accent-green' : 'bg-bg-tertiary text-text-tertiary'}`}>
                      {card.owned ? `Owned (${card.owned_qty})` : 'Missing'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Card detail popup */}
      {selectedCard && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={() => setSelectedCard(null)}>
          <div className="bg-bg-secondary rounded-xl border border-border-primary shadow-lg max-w-2xl w-full mx-4 p-6 animate-fade-in" onClick={e => e.stopPropagation()}>
            <div className="flex gap-5">
              <CardImage src={selectedCard.image_url} alt={selectedCard.name} size="lg" />
              <div className="flex-1 space-y-3">
                <h3 className="text-lg font-bold text-text-primary">{selectedCard.name}</h3>
                <p className="text-sm text-text-secondary">{selectedCard.type_line}</p>
                <ManaSymbols cost={selectedCard.mana_cost} size="md" />
                <p className="text-sm text-text-primary whitespace-pre-wrap">{selectedCard.reason}</p>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-text-tertiary">Role: <span className="text-accent-blue">{selectedCard.role}</span></span>
                  {selectedCard.is_substitute && (
                    <span className="text-accent-amber">Substituted for {selectedCard.original_name} ({(selectedCard.similarity_score ?? 0 * 100).toFixed(0)}%)</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Auto Gen Page ────────────────────────────────────────
export function AutoGenPage() {
  const [status, setStatus] = useState<DeckGenV3Status | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<DeckGenV3Result | null>(null)
  const [commander, setCommander] = useState<CommanderSearchResult | null>(null)
  const [strategy, setStrategy] = useState('')
  const [bracket, setBracket] = useState(3)
  const [budget, setBudget] = useState<string>('')
  const [useCollection, setUseCollection] = useState(true)
  const [runSub, setRunSub] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    deckgenApi.getV3Status().then(s => { setStatus(s); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  async function handleGenerate() {
    if (!commander) return
    setGenerating(true)
    setError(null)
    setResult(null)
    try {
      const res = await deckgenApi.generateDeckV3({
        commander_name: commander.name,
        strategy: strategy || undefined,
        target_bracket: bracket,
        budget_usd: budget ? Number(budget) : undefined,
        use_collection: useCollection,
        run_substitution: runSub,
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generation failed')
    }
    setGenerating(false)
  }

  async function handleCommit() {
    if (!commander || !result) return
    try {
      await deckgenApi.commitDeckV3({
        commander_name: commander.name,
        strategy: strategy || undefined,
        target_bracket: bracket,
        budget_usd: budget ? Number(budget) : undefined,
        use_collection: useCollection,
        run_substitution: runSub,
      })
    } catch { /* ignore */ }
  }

  if (loading) {
    return <div className="p-6 flex items-center justify-center h-64"><Spinner size="lg" className="text-accent-blue" /></div>
  }

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
          <Sparkles className="w-6 h-6 text-accent-purple" />
          Auto Gen V3
        </h1>
        <p className="text-sm text-text-secondary mt-0.5">AI-powered deck generation with Perplexity</p>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-3">
        <StatusBadge
          variant={status?.initialized ? 'success' : 'error'}
          label={status?.initialized ? 'Ready' : 'Not Initialized'}
        />
        <StatusBadge
          variant={status?.pplx_configured ? 'success' : 'warning'}
          label={status?.pplx_configured ? 'Perplexity Connected' : 'Perplexity Not Set'}
        />
        {status?.embeddings_loaded && (
          <StatusBadge variant="info" label={`${status.embedding_cards.toLocaleString()} embeddings`} />
        )}
      </div>

      {!result ? (
        /* Config form */
        <div className="max-w-2xl space-y-5">
          <div>
            <label className="text-sm font-medium text-text-primary block mb-2">Commander</label>
            <CommanderSearch onSelect={setCommander} />
            {commander && (
              <div className="mt-2 flex items-center gap-3 p-3 bg-bg-secondary rounded-lg border border-border-primary">
                <CardImage src={commander.image_url} alt={commander.name} size="sm" />
                <div>
                  <p className="text-sm font-medium text-text-primary">{commander.name}</p>
                  <p className="text-xs text-text-secondary">{commander.type_line}</p>
                </div>
                <ColorDots colors={commander.color_identity} />
              </div>
            )}
          </div>

          <div>
            <label className="text-sm font-medium text-text-primary block mb-2">Strategy (optional)</label>
            <input
              type="text"
              placeholder="e.g. Voltron, Aristocrats, Storm..."
              value={strategy}
              onChange={e => setStrategy(e.target.value)}
              className="w-full px-4 py-3 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-text-primary block mb-2">Target Bracket</label>
              <select
                value={bracket}
                onChange={e => setBracket(Number(e.target.value))}
                className="w-full px-4 py-3 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 transition-all"
              >
                <option value={1}>1 — Casual</option>
                <option value={2}>2 — Low Power</option>
                <option value={3}>3 — Mid Power</option>
                <option value={4}>4 — High Power</option>
              </select>
            </div>
            <div>
              <label className="text-sm font-medium text-text-primary block mb-2">Budget (USD, optional)</label>
              <input
                type="number"
                placeholder="No limit"
                value={budget}
                onChange={e => setBudget(e.target.value)}
                className="w-full px-4 py-3 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
              />
            </div>
          </div>

          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={useCollection} onChange={e => setUseCollection(e.target.checked)}
                className="w-4 h-4 rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30" />
              <span className="text-sm text-text-secondary">Use collection cards</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={runSub} onChange={e => setRunSub(e.target.checked)}
                className="w-4 h-4 rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30" />
              <span className="text-sm text-text-secondary">Run substitution pass</span>
            </label>
          </div>

          {error && (
            <div className="flex items-center gap-2 px-4 py-3 bg-status-error/10 border border-status-error/30 rounded-lg text-sm text-status-error">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <button
            onClick={handleGenerate}
            disabled={!commander || generating || !status?.initialized}
            className="flex items-center gap-2 px-6 py-3 bg-accent-blue text-white text-sm font-semibold rounded-lg hover:bg-accent-blue-hover shadow-glow-blue transition-all disabled:opacity-50 disabled:shadow-none"
          >
            {generating ? (
              <><Spinner size="sm" /> Generating...</>
            ) : (
              <><Wand2 className="w-4 h-4" /> Generate Deck</>
            )}
          </button>
        </div>
      ) : (
        /* Results */
        <div>
          <button onClick={() => setResult(null)}
            className="flex items-center gap-2 mb-4 text-sm text-text-secondary hover:text-text-primary transition-colors">
            <ChevronDown className="w-4 h-4 rotate-90" />
            Back to Config
          </button>
          <GeneratedDeckView result={result} onCommit={handleCommit} />
        </div>
      )}
    </div>
  )
}
