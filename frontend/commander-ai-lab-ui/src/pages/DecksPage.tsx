import { useState, useEffect } from 'react'
import {
  Plus, Trash2, Download, ChevronRight,
  BarChart3, Lightbulb, Layers, X
} from 'lucide-react'
import { Spinner, EmptyState, ManaSymbols, CardImage, ColorDots } from '../components/common'
import { decksApi } from '../api'
import type { Deck, DeckCard, DeckAnalysis, DeckRecommendation } from '../types'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

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

// ── Deck Detail View ──────────────────────────────────────────
function DeckDetail({ deck, onBack }: { deck: Deck; onBack: () => void }) {
  const [cards, setCards] = useState<DeckCard[]>([])
  const [analysis, setAnalysis] = useState<DeckAnalysis | null>(null)
  const [recs, setRecs] = useState<DeckRecommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'cards' | 'analysis' | 'recs'>('cards')
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

  async function loadRecs() {
    try {
      const r = await decksApi.getCollectionRecs(deck.id)
      setRecs(r)
    } catch { /* ignore */ }
  }

  useEffect(() => { if (tab === 'recs' && recs.length === 0) loadRecs() }, [tab])

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
        <div className="space-y-3">
          {recs.length === 0 ? (
            <EmptyState icon={Lightbulb} title="No recommendations yet" description="Recommendations are generated from your collection." />
          ) : (
            recs.map(rec => (
              <div key={rec.scryfall_id} className="flex items-center gap-4 p-3 bg-bg-secondary rounded-xl border border-border-primary hover:border-border-secondary transition-colors">
                <CardImage src={rec.image_url} alt={rec.name} size="sm" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-text-primary">{rec.name}</p>
                  <p className="text-xs text-text-secondary truncate">{rec.reason}</p>
                </div>
                <ManaSymbols cost={rec.mana_cost} />
                <span className="text-xs text-accent-teal">{rec.tcg_price != null ? `$${rec.tcg_price.toFixed(2)}` : ''}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${rec.owned ? 'bg-accent-green/15 text-accent-green' : 'bg-bg-tertiary text-text-tertiary'}`}>
                  {rec.owned ? 'Owned' : 'Missing'}
                </span>
              </div>
            ))
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
