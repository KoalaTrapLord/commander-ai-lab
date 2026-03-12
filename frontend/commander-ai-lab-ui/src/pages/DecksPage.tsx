import { useState, useEffect } from 'react'
import {
  Plus, Trash2, Download, ChevronRight,
  BarChart3, Lightbulb, Layers, X, Library,
  Globe, XCircle, ShoppingCart,
  ChevronDown, ChevronUp, Sparkles
} from 'lucide-react'
import { Spinner, EmptyState, ManaSymbols, ColorDots } from '../components/common'
import { decksApi } from '../api'
import type {
  Deck, DeckCard, DeckAnalysis,
  EdhRecCard, EdhRecsResponse,
  CollectionRecsResponse
} from '../types'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

// ── Role Badge ──────────────────────────────────────────────
const ROLE_COLORS: Record<string, string> = {
  Ramp: 'bg-green-500/15 text-green-400 border-green-500/25',
  Draw: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  Removal: 'bg-red-500/15 text-red-400 border-red-500/25',
  BoardWipe: 'bg-orange-500/15 text-orange-400 border-orange-500/25',
  Tutor: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  Protection: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
  Finisher: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/25',
  Recursion: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  Other: 'bg-slate-500/15 text-slate-400 border-slate-500/25',
}

function RoleBadge({ role }: { role: string }) {
  const colors = ROLE_COLORS[role] || ROLE_COLORS.Other
  return (
    <span className={'text-[10px] font-medium px-1.5 py-0.5 rounded border ' + colors}>
      {role}
    </span>
  )
}

// ── Deck Card List ────────────────────────────────────────────
function DeckCardList({ deckId, cards, onUpdate }: { deckId: number; cards: DeckCard[]; onUpdate: () => void }) {
  const [removing, setRemoving] = useState<number | null>(null)

  // Group cards by category
  const grouped = cards.reduce<Record<string, DeckCard[]>>((acc, c) => {
    const cat = c.category || 'Other'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(c)
    return acc
  }, {})

  const categoryOrder = ['Commander', 'Creature', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Land', 'Other']
  const sortedCategories = Object.keys(grouped).sort((a, b) => {
    const ia = categoryOrder.indexOf(a)
    const ib = categoryOrder.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })

  async function handleRemove(cardId: number) {
    setRemoving(cardId)
    try {
      await decksApi.removeCardFromDeck(deckId, cardId)
      onUpdate()
    } catch { /* ignore */ }
    setRemoving(null)
  }

  return (
    <div className="space-y-4">
      {sortedCategories.map(cat => (
        <div key={cat}>
          <h4 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider mb-2">
            {cat} ({grouped[cat].length})
          </h4>
          <div className="space-y-1">
            {grouped[cat].map(card => (
              <div key={card.id} className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-bg-hover group transition-colors">
                <span className="text-xs text-text-tertiary w-5 text-right">{card.quantity}x</span>
                <ManaSymbols cost={card.mana_cost} />
                <span className="flex-1 text-sm text-text-primary truncate">{card.name}</span>
                {card.tcg_price != null && (
                  <span className="text-xs text-accent-teal">${card.tcg_price.toFixed(2)}</span>
                )}
                {!card.is_commander && (
                  <button
                    onClick={() => handleRemove(card.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 text-text-tertiary hover:text-accent-red transition-all"
                  >
                    {removing === card.id ? <Spinner size="sm" /> : <Trash2 className="w-3.5 h-3.5" />}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Mana Curve Chart ──────────────────────────────────────────
function ManaCurveChart({ analysis }: { analysis: DeckAnalysis }) {
  const data = Object.entries(analysis.mana_curve)
    .map(([cmc, count]) => ({ cmc: cmc === '7' ? '7+' : cmc, count }))
    .sort((a, b) => Number(a.cmc) - Number(b.cmc))

  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barSize={24}>
          <XAxis dataKey="cmc" axisLine={false} tickLine={false} tick={{ fill: '#6b7190', fontSize: 11 }} />
          <YAxis hide />
          <Tooltip
            contentStyle={{ backgroundColor: '#1c2030', border: '1px solid #2a2f42', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#9ba1b8' }}
            itemStyle={{ color: '#e8eaf0' }}
          />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill="#4f6ef7" fillOpacity={0.8} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── EDHREC Recommendations Sub-tab ──────────────────────────
function EdhRecTab({ deckId, onAddedCards }: { deckId: number; onAddedCards: () => void }) {
  const [data, setData] = useState<EdhRecsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [onlyOwned, setOnlyOwned] = useState(false)
  const [selectedCards, setSelectedCards] = useState<Set<string>>(new Set())
  const [addingCards, setAddingCards] = useState<Set<string>>(new Set())
  const [bulkAdding, setBulkAdding] = useState(false)
  const [hoveredCard, setHoveredCard] = useState<EdhRecCard | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())

  async function fetchRecs() {
    setLoading(true)
    setError(null)
    try {
      const result = await decksApi.getEdhRecs(deckId, onlyOwned)
      setData(result)
    } catch (e: any) {
      setError(e?.message || 'Failed to load EDHREC recommendations')
    }
    setLoading(false)
  }

  useEffect(() => { fetchRecs() }, [deckId, onlyOwned])

  function toggleSelect(name: string) {
    setSelectedCards(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function selectAll() {
    if (!data) return
    setSelectedCards(new Set(data.recommendations.map(r => r.name)))
  }

  function selectNone() { setSelectedCards(new Set()) }

  function selectOwned() {
    if (!data) return
    setSelectedCards(new Set(data.recommendations.filter(r => r.owned).map(r => r.name)))
  }

  async function handleAddSingle(name: string) {
    setAddingCards(prev => new Set(prev).add(name))
    try {
      await decksApi.bulkAddRecommended(deckId, [name])
      onAddedCards()
      // Remove from list
      if (data) {
        setData({
          ...data,
          recommendations: data.recommendations.filter(r => r.name !== name),
          total: data.total - 1,
        })
      }
      selectedCards.delete(name)
      setSelectedCards(new Set(selectedCards))
    } catch { /* ignore */ }
    setAddingCards(prev => { const n = new Set(prev); n.delete(name); return n })
  }

  async function handleBulkAdd() {
    if (selectedCards.size === 0) return
    setBulkAdding(true)
    try {
      await decksApi.bulkAddRecommended(deckId, Array.from(selectedCards))
      onAddedCards()
      if (data) {
        setData({
          ...data,
          recommendations: data.recommendations.filter(r => !selectedCards.has(r.name)),
          total: data.total - selectedCards.size,
        })
      }
      setSelectedCards(new Set())
    } catch { /* ignore */ }
    setBulkAdding(false)
  }

  function toggleGroup(groupName: string) {
    setCollapsedGroups(prev => {
      const next = new Set(prev)
      if (next.has(groupName)) next.delete(groupName)
      else next.add(groupName)
      return next
    })
  }

  // Group recommendations by role
  function groupByRole(recs: EdhRecCard[]): Record<string, EdhRecCard[]> {
    const groups: Record<string, EdhRecCard[]> = {}
    for (const rec of recs) {
      const role = rec.role || 'Other'
      if (!groups[role]) groups[role] = []
      groups[role].push(rec)
    }
    return groups
  }

  if (loading) {
    return <div className="flex items-center justify-center h-40"><Spinner size="lg" className="text-accent-blue" /></div>
  }

  if (error) {
    return (
      <div className="bg-accent-red/10 border border-accent-red/20 rounded-xl p-5 text-center">
        <XCircle className="w-6 h-6 text-accent-red mx-auto mb-2" />
        <p className="text-sm text-accent-red font-medium">{error}</p>
        <button onClick={fetchRecs} className="mt-3 px-4 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors">
          Retry
        </button>
      </div>
    )
  }

  if (!data || data.recommendations.length === 0) {
    return <EmptyState icon={Globe} title="No EDHREC data" description="No recommendations found for this commander on EDHREC." />
  }

  const grouped = groupByRole(data.recommendations)
  const roleOrder = ['Ramp', 'Draw', 'Removal', 'BoardWipe', 'Tutor', 'Protection', 'Finisher', 'Recursion', 'Other']
  const sortedRoles = Object.keys(grouped).sort((a, b) => {
    const ia = roleOrder.indexOf(a)
    const ib = roleOrder.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })

  const ownedCount = data.recommendations.filter(r => r.owned).length
  const missingCount = data.recommendations.length - ownedCount

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-sm">
            <Sparkles className="w-4 h-4 text-accent-blue" />
            <span className="text-text-primary font-medium">{data.commander}</span>
            <span className="text-text-tertiary">via {data.source}</span>
          </div>
          <span className="text-xs px-2 py-0.5 rounded bg-accent-green/15 text-accent-green">{ownedCount} owned</span>
          <span className="text-xs px-2 py-0.5 rounded bg-bg-tertiary text-text-tertiary">{missingCount} missing</span>
        </div>
        <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyOwned}
            onChange={e => setOnlyOwned(e.target.checked)}
            className="rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30 w-3.5 h-3.5"
          />
          Show only owned
        </label>
      </div>

      {/* Selection toolbar */}
      <div className="flex items-center justify-between bg-bg-secondary rounded-xl border border-border-primary px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Select:</span>
          <button onClick={selectAll} className="text-xs text-accent-blue hover:underline">All</button>
          <span className="text-text-tertiary">/</span>
          <button onClick={selectNone} className="text-xs text-accent-blue hover:underline">None</button>
          <span className="text-text-tertiary">/</span>
          <button onClick={selectOwned} className="text-xs text-accent-blue hover:underline">Owned</button>
          {selectedCards.size > 0 && (
            <span className="text-xs text-text-secondary ml-2">({selectedCards.size} selected)</span>
          )}
        </div>
        <button
          onClick={handleBulkAdd}
          disabled={selectedCards.size === 0 || bulkAdding}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-accent-blue text-white rounded-lg hover:bg-accent-blue-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {bulkAdding ? <Spinner size="sm" /> : <ShoppingCart className="w-3.5 h-3.5" />}
          Add {selectedCards.size > 0 ? selectedCards.size : ''} to Deck
        </button>
      </div>

      {/* Grouped cards */}
      {sortedRoles.map(role => {
        const cards = grouped[role]
        const isCollapsed = collapsedGroups.has(role)
        return (
          <div key={role} className="bg-bg-secondary rounded-xl border border-border-primary overflow-hidden">
            {/* Group header */}
            <button
              onClick={() => toggleGroup(role)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-bg-hover transition-colors"
            >
              <div className="flex items-center gap-2">
                <RoleBadge role={role} />
                <span className="text-xs text-text-tertiary">({cards.length})</span>
              </div>
              {isCollapsed ? <ChevronDown className="w-4 h-4 text-text-tertiary" /> : <ChevronUp className="w-4 h-4 text-text-tertiary" />}
            </button>
            {/* Card list */}
            {!isCollapsed && (
              <div className="border-t border-border-primary divide-y divide-border-primary">
                {cards.map(rec => (
                  <div
                    key={rec.name}
                    className="flex items-center gap-3 px-4 py-2.5 hover:bg-bg-hover transition-colors group relative"
                    onMouseEnter={() => setHoveredCard(rec)}
                    onMouseLeave={() => setHoveredCard(null)}
                  >
                    {/* Checkbox */}
                    <input
                      type="checkbox"
                      checked={selectedCards.has(rec.name)}
                      onChange={() => toggleSelect(rec.name)}
                      className="rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30 w-3.5 h-3.5 flex-shrink-0"
                    />
                    {/* Card image mini */}
                    {rec.image_url && (
                      <div className="w-8 h-11 rounded overflow-hidden bg-bg-tertiary flex-shrink-0">
                        <img src={rec.image_url} alt={rec.name} className="w-full h-full object-cover" loading="lazy" />
                      </div>
                    )}
                    {/* Card info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">{rec.name}</p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-[10px] text-text-tertiary truncate">{rec.type_line}</span>
                        {rec.roles.length > 0 && rec.roles.map(r => <RoleBadge key={r} role={r} />)}
                      </div>
                    </div>
                    {/* Owned badge */}
                    <span className={'text-xs px-2 py-0.5 rounded flex-shrink-0 ' + (rec.owned ? 'bg-accent-green/15 text-accent-green' : 'bg-bg-tertiary text-text-tertiary')}>
                      {rec.owned ? (rec.owned_qty + 'x owned') : 'Missing'}
                    </span>
                    {/* Add button */}
                    <button
                      onClick={e => { e.stopPropagation(); handleAddSingle(rec.name) }}
                      disabled={addingCards.has(rec.name)}
                      className="opacity-0 group-hover:opacity-100 px-2.5 py-1 text-xs font-medium bg-accent-blue text-white rounded-lg hover:bg-accent-blue-hover transition-all disabled:opacity-50 flex-shrink-0"
                    >
                      {addingCards.has(rec.name) ? <Spinner size="sm" /> : '+ Add'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* Hover preview */}
      {hoveredCard && hoveredCard.image_url && (
        <div className="fixed top-20 right-8 z-50 pointer-events-none animate-fade-in">
          <img
            src={hoveredCard.image_url}
            alt={hoveredCard.name}
            className="w-[244px] rounded-xl shadow-2xl shadow-black/60 border border-border-primary"
          />
        </div>
      )}
    </div>
  )
}

// ── Collection Recommendations Sub-tab ──────────────────────
function CollectionRecTab({ deckId, onAddedCards }: { deckId: number; onAddedCards: () => void }) {
  const [data, setData] = useState<CollectionRecsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCards, setSelectedCards] = useState<Set<string>>(new Set())
  const [addingCards, setAddingCards] = useState<Set<string>>(new Set())
  const [bulkAdding, setBulkAdding] = useState(false)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())

  async function fetchRecs() {
    setLoading(true)
    setError(null)
    try {
      const result = await decksApi.getCollectionRecs(deckId)
      setData(result)
    } catch (e: any) {
      setError(e?.message || 'Failed to load collection recommendations')
    }
    setLoading(false)
  }

  useEffect(() => { fetchRecs() }, [deckId])

  function toggleSelect(name: string) {
    setSelectedCards(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function selectAll() {
    if (!data) return
    const all = new Set<string>()
    Object.values(data.grouped).flat().forEach(c => all.add(c.name))
    setSelectedCards(all)
  }

  function selectNone() { setSelectedCards(new Set()) }

  async function handleAddSingle(name: string) {
    setAddingCards(prev => new Set(prev).add(name))
    try {
      await decksApi.bulkAddRecommended(deckId, [name])
      onAddedCards()
      // Remove from groupings
      if (data) {
        const newGrouped = { ...data.grouped }
        for (const key of Object.keys(newGrouped)) {
          newGrouped[key] = newGrouped[key].filter(c => c.name !== name)
          if (newGrouped[key].length === 0) delete newGrouped[key]
        }
        setData({ ...data, grouped: newGrouped, total: data.total - 1 })
      }
      selectedCards.delete(name)
      setSelectedCards(new Set(selectedCards))
    } catch { /* ignore */ }
    setAddingCards(prev => { const n = new Set(prev); n.delete(name); return n })
  }

  async function handleBulkAdd() {
    if (selectedCards.size === 0) return
    setBulkAdding(true)
    try {
      await decksApi.bulkAddRecommended(deckId, Array.from(selectedCards))
      onAddedCards()
      if (data) {
        const newGrouped = { ...data.grouped }
        for (const key of Object.keys(newGrouped)) {
          newGrouped[key] = newGrouped[key].filter(c => !selectedCards.has(c.name))
          if (newGrouped[key].length === 0) delete newGrouped[key]
        }
        setData({ ...data, grouped: newGrouped, total: data.total - selectedCards.size })
      }
      setSelectedCards(new Set())
    } catch { /* ignore */ }
    setBulkAdding(false)
  }

  function toggleGroup(groupName: string) {
    setCollapsedGroups(prev => {
      const next = new Set(prev)
      if (next.has(groupName)) next.delete(groupName)
      else next.add(groupName)
      return next
    })
  }

  if (loading) {
    return <div className="flex items-center justify-center h-40"><Spinner size="lg" className="text-accent-blue" /></div>
  }

  if (error) {
    return (
      <div className="bg-accent-red/10 border border-accent-red/20 rounded-xl p-5 text-center">
        <XCircle className="w-6 h-6 text-accent-red mx-auto mb-2" />
        <p className="text-sm text-accent-red font-medium">{error}</p>
        <button onClick={fetchRecs} className="mt-3 px-4 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors">
          Retry
        </button>
      </div>
    )
  }

  if (!data || data.total === 0) {
    return <EmptyState icon={Library} title="No collection matches" description="No cards in your collection match this deck's needs." />
  }

  const typeOrder = ['Creature', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Land', 'Other']
  const sortedTypes = Object.keys(data.grouped).sort((a, b) => {
    const ia = typeOrder.indexOf(a)
    const ib = typeOrder.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })

  return (
    <div className="space-y-4">
      {/* Shortfall alert */}
      {data.shortfall_types.length > 0 && (
        <div className="flex items-start gap-3 bg-accent-blue/8 border border-accent-blue/20 rounded-xl px-4 py-3">
          <Lightbulb className="w-4 h-4 text-accent-blue mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-xs font-medium text-accent-blue">Deck needs more:</p>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {data.shortfall_types.map(t => (
                <span key={t} className="text-[10px] font-medium px-2 py-0.5 rounded bg-accent-blue/15 text-accent-blue border border-accent-blue/25">{t}</span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Selection toolbar */}
      <div className="flex items-center justify-between bg-bg-secondary rounded-xl border border-border-primary px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Select:</span>
          <button onClick={selectAll} className="text-xs text-accent-blue hover:underline">All</button>
          <span className="text-text-tertiary">/</span>
          <button onClick={selectNone} className="text-xs text-accent-blue hover:underline">None</button>
          {selectedCards.size > 0 && (
            <span className="text-xs text-text-secondary ml-2">({selectedCards.size} selected)</span>
          )}
        </div>
        <button
          onClick={handleBulkAdd}
          disabled={selectedCards.size === 0 || bulkAdding}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-accent-blue text-white rounded-lg hover:bg-accent-blue-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {bulkAdding ? <Spinner size="sm" /> : <ShoppingCart className="w-3.5 h-3.5" />}
          Add {selectedCards.size > 0 ? selectedCards.size : ''} to Deck
        </button>
      </div>

      {/* Grouped cards */}
      {sortedTypes.map(type => {
        const cards = data.grouped[type]
        const isCollapsed = collapsedGroups.has(type)
        const isShortfall = data.shortfall_types.includes(type)
        return (
          <div key={type} className={'bg-bg-secondary rounded-xl border overflow-hidden ' + (isShortfall ? 'border-accent-blue/30' : 'border-border-primary')}>
            {/* Group header */}
            <button
              onClick={() => toggleGroup(type)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-bg-hover transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-text-primary uppercase tracking-wider">{type}</span>
                <span className="text-xs text-text-tertiary">({cards.length})</span>
                {isShortfall && <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-accent-blue/15 text-accent-blue border border-accent-blue/25">Shortfall</span>}
              </div>
              {isCollapsed ? <ChevronDown className="w-4 h-4 text-text-tertiary" /> : <ChevronUp className="w-4 h-4 text-text-tertiary" />}
            </button>
            {/* Card list */}
            {!isCollapsed && (
              <div className="border-t border-border-primary divide-y divide-border-primary">
                {cards.map(rec => (
                  <div key={rec.scryfall_id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-bg-hover transition-colors group">
                    {/* Checkbox */}
                    <input
                      type="checkbox"
                      checked={selectedCards.has(rec.name)}
                      onChange={() => toggleSelect(rec.name)}
                      className="rounded border-border-primary bg-bg-tertiary text-accent-blue focus:ring-accent-blue/30 w-3.5 h-3.5 flex-shrink-0"
                    />
                    {/* Card image mini */}
                    {rec.image_url && (
                      <div className="w-8 h-11 rounded overflow-hidden bg-bg-tertiary flex-shrink-0">
                        <img src={rec.image_url} alt={rec.name} className="w-full h-full object-cover" loading="lazy" />
                      </div>
                    )}
                    {/* Card info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">{rec.name}</p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-[10px] text-text-tertiary">{rec.cmc} CMC</span>
                        {rec.roles.length > 0 && rec.roles.map(r => <RoleBadge key={r} role={r} />)}
                      </div>
                    </div>
                    {/* Score */}
                    <span className="text-xs text-accent-teal font-medium flex-shrink-0">Score: {rec.score}</span>
                    {/* Owned qty */}
                    <span className="text-xs px-2 py-0.5 rounded bg-accent-green/15 text-accent-green flex-shrink-0">{rec.owned_qty}x</span>
                    {/* Add button */}
                    <button
                      onClick={e => { e.stopPropagation(); handleAddSingle(rec.name) }}
                      disabled={addingCards.has(rec.name)}
                      className="opacity-0 group-hover:opacity-100 px-2.5 py-1 text-xs font-medium bg-accent-blue text-white rounded-lg hover:bg-accent-blue-hover transition-all disabled:opacity-50 flex-shrink-0"
                    >
                      {addingCards.has(rec.name) ? <Spinner size="sm" /> : '+ Add'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Deck Detail View ──────────────────────────────────────────
function DeckDetail({ deck, onBack }: { deck: Deck; onBack: () => void }) {
  const [cards, setCards] = useState<DeckCard[]>([])
  const [analysis, setAnalysis] = useState<DeckAnalysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'cards' | 'analysis' | 'recs'>('cards')
  const [recSource, setRecSource] = useState<'edhrec' | 'collection'>('edhrec')
  const [addingCard, setAddingCard] = useState('')
  const [bulkText, setBulkText] = useState('')
  const [showBulk, setShowBulk] = useState(false)

  async function fetchAll() {
    setLoading(true)
    try {
      const [c, a] = await Promise.all([
        decksApi.getDeckCards(deck.id),
        decksApi.getDeckAnalysis(deck.id),
      ])
      setCards(c)
      setAnalysis(a)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { fetchAll() }, [deck.id])

  async function handleAddCard() {
    if (!addingCard.trim()) return
    try {
      await decksApi.addCardToDeck(deck.id, { name: addingCard.trim() })
      setAddingCard('')
      fetchAll()
    } catch { /* ignore */ }
  }

  async function handleBulkAdd() {
    if (!bulkText.trim()) return
    const cardLines = bulkText.split('\n').filter(l => l.trim())
    const cardParsed = cardLines.map(l => {
      const match = l.match(/^(\d+)x?\s+(.+)$/)
      return match ? { name: match[2].trim(), quantity: Number(match[1]) } : { name: l.trim() }
    })
    try {
      await decksApi.bulkAddCards(deck.id, cardParsed)
      setBulkText('')
      setShowBulk(false)
      fetchAll()
    } catch { /* ignore */ }
  }

  async function handleExportToSim() {
    try {
      await decksApi.exportDeckToSim(deck.id)
    } catch { /* ignore */ }
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={onBack} className="p-2 rounded-lg hover:bg-bg-hover text-text-secondary transition-colors">
          <ChevronRight className="w-5 h-5 rotate-180" />
        </button>
        <div className="flex-1">
          <h2 className="text-xl font-bold text-text-primary">{deck.name}</h2>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-sm text-text-secondary">{deck.commander}</span>
            <ColorDots colors={deck.color_identity} />
            <span className="text-xs text-text-tertiary">{deck.card_count} cards</span>
            <span className="text-xs text-accent-teal">${deck.total_price.toFixed(2)}</span>
          </div>
        </div>
        <button onClick={handleExportToSim}
          className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors">
          <Download className="w-3.5 h-3.5" />
          Export to Sim
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border-primary">
        {(['cards', 'analysis', 'recs'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors capitalize ${
              tab === t
                ? 'border-accent-blue text-accent-blue'
                : 'border-transparent text-text-tertiary hover:text-text-secondary'
            }`}
          >
            {t === 'recs' ? 'Recommendations' : t}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40"><Spinner size="lg" className="text-accent-blue" /></div>
      ) : tab === 'cards' ? (
        <div className="space-y-4">
          {/* Add card */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Add card by name..."
              value={addingCard}
              onChange={e => setAddingCard(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAddCard()}
              className="flex-1 px-4 py-2.5 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
            />
            <button onClick={handleAddCard}
              className="px-4 py-2.5 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors">
              Add
            </button>
            <button onClick={() => setShowBulk(!showBulk)}
              className="px-3 py-2.5 bg-bg-tertiary text-text-secondary text-sm rounded-lg hover:bg-bg-hover border border-border-primary transition-colors">
              <Layers className="w-4 h-4" />
            </button>
          </div>
          {showBulk && (
            <div className="bg-bg-secondary rounded-xl border border-border-primary p-4 animate-fade-in space-y-3">
              <textarea
                placeholder={"1x Sol Ring\n1x Command Tower\n2x Counterspell"}
                value={bulkText}
                onChange={e => setBulkText(e.target.value)}
                rows={6}
                className="w-full px-4 py-3 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary font-mono focus:outline-none focus:border-accent-blue/50 transition-all resize-none"
              />
              <button onClick={handleBulkAdd}
                className="px-4 py-2 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors">
                Bulk Add
              </button>
            </div>
          )}
          <DeckCardList deckId={deck.id} cards={cards} onUpdate={fetchAll} />
        </div>
      ) : tab === 'analysis' && analysis ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Stats */}
          <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4">
            <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-accent-blue" />
              Deck Stats
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Cards', value: analysis.card_count },
                { label: 'Lands', value: analysis.land_count },
                { label: 'Creatures', value: analysis.creature_count },
                { label: 'Non-Creature', value: analysis.noncreature_count },
                { label: 'Avg CMC', value: analysis.avg_cmc.toFixed(2) },
                { label: 'Owned', value: `${analysis.owned_count} / ${analysis.card_count}` },
              ].map(stat => (
                <div key={stat.label} className="px-3 py-2 rounded-lg bg-bg-tertiary">
                  <p className="text-xs text-text-tertiary">{stat.label}</p>
                  <p className="text-lg font-bold text-text-primary">{stat.value}</p>
                </div>
              ))}
            </div>
          </div>
          {/* Mana Curve */}
          <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-4">
            <h3 className="text-sm font-semibold text-text-primary">Mana Curve</h3>
            <ManaCurveChart analysis={analysis} />
          </div>
          {/* Type Distribution */}
          <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-3 md:col-span-2">
            <h3 className="text-sm font-semibold text-text-primary">Type Distribution</h3>
            <div className="flex flex-wrap gap-2">
              {Object.entries(analysis.type_distribution).map(([type, count]) => (
                <span key={type} className="px-3 py-1.5 bg-bg-tertiary rounded-lg text-xs text-text-secondary">
                  {type}: <span className="font-semibold text-text-primary">{count}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : tab === 'recs' ? (
        <div className="space-y-4">
          {/* Sub-tab toggle */}
          <div className="flex items-center gap-1 bg-bg-tertiary rounded-lg p-1 w-fit">
            <button
              onClick={() => setRecSource('edhrec')}
              className={'flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-md transition-all ' +
                (recSource === 'edhrec'
                  ? 'bg-accent-blue text-white shadow-sm'
                  : 'text-text-tertiary hover:text-text-secondary')}
            >
              <Globe className="w-3.5 h-3.5" />
              EDHREC
            </button>
            <button
              onClick={() => setRecSource('collection')}
              className={'flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-md transition-all ' +
                (recSource === 'collection'
                  ? 'bg-accent-blue text-white shadow-sm'
                  : 'text-text-tertiary hover:text-text-secondary')}
            >
              <Library className="w-3.5 h-3.5" />
              From Collection
            </button>
          </div>

          {/* Sub-tab content */}
          {recSource === 'edhrec' ? (
            <EdhRecTab deckId={deck.id} onAddedCards={fetchAll} />
          ) : (
            <CollectionRecTab deckId={deck.id} onAddedCards={fetchAll} />
          )}
        </div>
      ) : null}
    </div>
  )
}

// ── Main Decks Page ───────────────────────────────────────────
export function DecksPage() {
  const [decks, setDecks] = useState<Deck[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedDeck, setSelectedDeck] = useState<Deck | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newDeckName, setNewDeckName] = useState('')
  const [newCommander, setNewCommander] = useState('')
  const [creating, setCreating] = useState(false)

  async function fetchDecks() {
    setLoading(true)
    try {
      const d = await decksApi.listDecks()
      setDecks(d)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { fetchDecks() }, [])

  async function handleCreate() {
    if (!newDeckName.trim()) return
    setCreating(true)
    try {
      const deck = await decksApi.createDeck({ name: newDeckName.trim(), commander: newCommander.trim() || undefined })
      setNewDeckName('')
      setNewCommander('')
      setShowCreate(false)
      setSelectedDeck(deck)
      fetchDecks()
    } catch { /* ignore */ }
    setCreating(false)
  }

  async function handleDelete(deckId: number) {
    try {
      await decksApi.deleteDeck(deckId)
      fetchDecks()
    } catch { /* ignore */ }
  }

  if (selectedDeck) {
    return (
      <div className="p-6">
        <DeckDetail deck={selectedDeck} onBack={() => { setSelectedDeck(null); fetchDecks() }} />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Decks</h1>
          <p className="text-sm text-text-secondary mt-0.5">{decks.length} deck{decks.length !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Deck
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-5 animate-fade-in space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Create New Deck</h3>
            <button onClick={() => setShowCreate(false)} className="text-text-tertiary hover:text-text-secondary">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="Deck name"
              value={newDeckName}
              onChange={e => setNewDeckName(e.target.value)}
              className="px-4 py-2.5 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
            />
            <input
              type="text"
              placeholder="Commander (optional)"
              value={newCommander}
              onChange={e => setNewCommander(e.target.value)}
              className="px-4 py-2.5 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 transition-all"
            />
          </div>
          <button onClick={handleCreate} disabled={creating}
            className="px-4 py-2 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors disabled:opacity-50">
            {creating ? <Spinner size="sm" /> : 'Create'}
          </button>
        </div>
      )}

      {/* Deck list */}
      {loading ? (
        <div className="flex items-center justify-center h-40"><Spinner size="lg" className="text-accent-blue" /></div>
      ) : decks.length === 0 ? (
        <EmptyState icon={Layers} title="No decks yet" description="Create your first deck to get started." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {decks.map(deck => (
            <div
              key={deck.id}
              className="bg-bg-secondary rounded-xl border border-border-primary hover:border-border-secondary p-5 cursor-pointer transition-all group"
              onClick={() => setSelectedDeck(deck)}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-text-primary truncate group-hover:text-accent-blue transition-colors">{deck.name}</h3>
                  <p className="text-sm text-text-secondary mt-0.5 truncate">{deck.commander}</p>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); handleDelete(deck.id) }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 text-text-tertiary hover:text-accent-red transition-all"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <ColorDots colors={deck.color_identity} />
                  <span className="text-xs text-text-tertiary">{deck.card_count} cards</span>
                </div>
                <span className="text-xs font-medium text-accent-teal">${deck.total_price.toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
