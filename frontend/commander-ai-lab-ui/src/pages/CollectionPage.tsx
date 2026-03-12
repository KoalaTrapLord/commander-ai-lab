import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Search, Filter, Upload, Download, Camera, RefreshCw,
  ChevronLeft, ChevronRight, X, Package, SlidersHorizontal,
  Plus, Grid3x3, List
} from 'lucide-react'
import { Spinner, EmptyState, ManaSymbols, CardImage } from '../components/common'
import { collectionApi } from '../api'
import type { CollectionCard, CollectionFilters, SetInfo } from '../types'

// ── Card Detail Modal ─────────────────────────────────────────
function CardDetailModal({ card, onClose }: { card: CollectionCard; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-bg-secondary rounded-xl border border-border-primary shadow-lg max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto animate-fade-in"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between p-5 border-b border-border-primary">
          <div>
            <h2 className="text-xl font-bold text-text-primary">{card.name}</h2>
            <p className="text-sm text-text-secondary mt-0.5">{card.type_line}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-bg-hover text-text-tertiary">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex flex-col md:flex-row gap-6 p-5">
          {/* Large card image */}
          <div className="flex-shrink-0">
            <CardImage src={card.image_url} alt={card.name} size="xl" />
          </div>
          {/* Card info */}
          <div className="flex-1 space-y-4">
            <div>
              <label className="text-xs text-text-tertiary uppercase tracking-wider">Mana Cost</label>
              <div className="mt-1"><ManaSymbols cost={card.mana_cost} size="md" /></div>
            </div>
            <div>
              <label className="text-xs text-text-tertiary uppercase tracking-wider">Oracle Text</label>
              <p className="mt-1 text-sm text-text-primary whitespace-pre-wrap leading-relaxed">{card.oracle_text}</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Set</label>
                <p className="mt-1 text-sm text-text-primary">{card.set_name} ({card.set_code.toUpperCase()})</p>
              </div>
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Rarity</label>
                <p className={`mt-1 text-sm font-medium capitalize ${
                  card.rarity === 'mythic' ? 'text-accent-amber' :
                  card.rarity === 'rare' ? 'text-accent-amber/80' :
                  card.rarity === 'uncommon' ? 'text-accent-teal' : 'text-text-secondary'
                }`}>{card.rarity}</p>
              </div>
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">CMC</label>
                <p className="mt-1 text-sm text-text-primary">{card.cmc}</p>
              </div>
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">EDHREC Rank</label>
                <p className="mt-1 text-sm text-text-primary">{card.edhrec_rank ?? 'N/A'}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Quantity</label>
                <p className="mt-1 text-sm text-text-primary">{card.quantity} (+ {card.foil_quantity} foil)</p>
              </div>
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Price</label>
                <p className="mt-1 text-sm text-accent-teal font-semibold">
                  ${card.tcg_price?.toFixed(2) ?? '—'}
                  {card.foil_price ? <span className="text-text-tertiary ml-2">Foil: ${card.foil_price.toFixed(2)}</span> : null}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Scanner Panel ─────────────────────────────────────────────
function ScannerPanel({ onCardAdded }: { onCardAdded: () => void }) {
  const [scanning, setScanning] = useState(false)
  const [results, setResults] = useState<import('../types').ScanMatch[]>([])
  const [adding, setAdding] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleScan(file: File) {
    setScanning(true)
    setResults([])
    try {
      const res = await collectionApi.scanCard(file)
      setResults(res.matches || [])
    } catch {
      setResults([])
    }
    setScanning(false)
  }

  async function handleAdd(match: import('../types').ScanMatch) {
    setAdding(match.scryfall_id)
    try {
      await collectionApi.addScanResult({
        name: match.name,
        set_code: match.set_code,
        scryfall_id: match.scryfall_id,
      })
      onCardAdded()
    } catch { /* ignore */ }
    setAdding(null)
  }

  return (
    <div className="bg-bg-secondary rounded-xl border border-border-primary p-5">
      <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
        <Camera className="w-4 h-4 text-accent-blue" />
        Card Scanner
      </h3>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={e => e.target.files?.[0] && handleScan(e.target.files[0])}
      />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={scanning}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent-blue/10 text-accent-blue border border-accent-blue/30 rounded-lg text-sm font-medium hover:bg-accent-blue/20 transition-colors disabled:opacity-50"
      >
        {scanning ? <Spinner size="sm" /> : <Camera className="w-4 h-4" />}
        {scanning ? 'Scanning...' : 'Scan a Card'}
      </button>
      {results.length > 0 && (
        <div className="mt-3 space-y-2 max-h-60 overflow-y-auto">
          {results.map(m => (
            <div key={m.scryfall_id} className="flex items-center gap-3 p-2 rounded-lg bg-bg-tertiary">
              <CardImage src={m.image_url} alt={m.name} size="sm" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary truncate">{m.name}</p>
                <p className="text-xs text-text-tertiary">{m.set_name} — {(m.confidence * 100).toFixed(0)}%</p>
              </div>
              <button
                onClick={() => handleAdd(m)}
                disabled={adding === m.scryfall_id}
                className="p-1.5 rounded-lg bg-accent-green/15 text-accent-green hover:bg-accent-green/25 transition-colors"
              >
                {adding === m.scryfall_id ? <Spinner size="sm" /> : <Plus className="w-4 h-4" />}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Collection Page ──────────────────────────────────────
export function CollectionPage() {
  const [cards, setCards] = useState<CollectionCard[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [sets, setSets] = useState<SetInfo[]>([])
  const [selectedCard, setSelectedCard] = useState<CollectionCard | null>(null)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [showFilters, setShowFilters] = useState(false)
  const [importing, setImporting] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const importRef = useRef<HTMLInputElement>(null)

  const [filters, setFilters] = useState<CollectionFilters>({
    q: '',
    page: 1,
    page_size: 48,
    sort_by: 'name',
    sort_dir: 'asc',
  })

  const fetchCards = useCallback(async () => {
    setLoading(true)
    try {
      const res = await collectionApi.searchCollection(filters)
      setCards(res.cards)
      setTotal(res.total)
    } catch { /* ignore */ }
    setLoading(false)
  }, [filters])

  useEffect(() => { fetchCards() }, [fetchCards])

  useEffect(() => {
    collectionApi.getSets().then(setSets).catch(() => {})
  }, [])

  const totalPages = Math.ceil(total / (filters.page_size || 48))

  function updateFilter(key: keyof CollectionFilters, value: string | number | boolean | undefined) {
    setFilters(prev => ({ ...prev, [key]: value, page: 1 }))
  }

  async function handleExport() {
    const blob = await collectionApi.exportCollection('csv')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'collection.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  async function handleImport(file: File) {
    setImporting(true)
    try {
      await collectionApi.importCollection(file)
      fetchCards()
    } catch { /* ignore */ }
    setImporting(false)
  }

  async function handleReEnrich() {
    setEnriching(true)
    try {
      await collectionApi.reEnrichCards()
      fetchCards()
    } catch { /* ignore */ }
    setEnriching(false)
  }

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Collection</h1>
          <p className="text-sm text-text-secondary mt-0.5">{total.toLocaleString()} cards in your collection</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleReEnrich} disabled={enriching}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors disabled:opacity-50">
            {enriching ? <Spinner size="sm" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Re-Enrich
          </button>
          <input ref={importRef} type="file" accept=".csv,.txt" className="hidden"
            onChange={e => e.target.files?.[0] && handleImport(e.target.files[0])} />
          <button onClick={() => importRef.current?.click()} disabled={importing}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors disabled:opacity-50">
            {importing ? <Spinner size="sm" /> : <Upload className="w-3.5 h-3.5" />}
            Import
          </button>
          <button onClick={handleExport}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-bg-tertiary text-text-secondary rounded-lg hover:bg-bg-hover border border-border-primary transition-colors">
            <Download className="w-3.5 h-3.5" />
            Export
          </button>
        </div>
      </div>

      <div className="flex gap-5">
        {/* Left sidebar: search + filters + scanner */}
        <div className="w-72 flex-shrink-0 space-y-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
            <input
              type="text"
              placeholder="Search cards..."
              value={filters.q || ''}
              onChange={e => updateFilter('q', e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue/50 focus:ring-1 focus:ring-accent-blue/30 transition-all"
            />
          </div>

          {/* Filter toggle */}
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="w-full flex items-center justify-between px-4 py-2.5 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-secondary hover:bg-bg-hover transition-colors"
          >
            <span className="flex items-center gap-2">
              <SlidersHorizontal className="w-4 h-4" />
              Filters
            </span>
            <Filter className={`w-3.5 h-3.5 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
          </button>

          {showFilters && (
            <div className="bg-bg-secondary rounded-xl border border-border-primary p-4 space-y-3 animate-fade-in">
              {/* Rarity */}
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Rarity</label>
                <select
                  value={filters.rarity || ''}
                  onChange={e => updateFilter('rarity', e.target.value || undefined)}
                  className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50"
                >
                  <option value="">All</option>
                  <option value="common">Common</option>
                  <option value="uncommon">Uncommon</option>
                  <option value="rare">Rare</option>
                  <option value="mythic">Mythic</option>
                </select>
              </div>
              {/* Color */}
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Color</label>
                <select
                  value={filters.color || ''}
                  onChange={e => updateFilter('color', e.target.value || undefined)}
                  className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50"
                >
                  <option value="">All</option>
                  <option value="W">White</option>
                  <option value="U">Blue</option>
                  <option value="B">Black</option>
                  <option value="R">Red</option>
                  <option value="G">Green</option>
                  <option value="C">Colorless</option>
                </select>
              </div>
              {/* Set */}
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Set</label>
                <select
                  value={filters.set_code || ''}
                  onChange={e => updateFilter('set_code', e.target.value || undefined)}
                  className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50"
                >
                  <option value="">All Sets</option>
                  {sets.map(s => (
                    <option key={s.code} value={s.code}>{s.name} ({s.card_count})</option>
                  ))}
                </select>
              </div>
              {/* CMC Range */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-text-tertiary uppercase tracking-wider">CMC Min</label>
                  <input type="number" min="0" max="20"
                    value={filters.cmc_min ?? ''}
                    onChange={e => updateFilter('cmc_min', e.target.value ? Number(e.target.value) : undefined)}
                    className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50"
                  />
                </div>
                <div>
                  <label className="text-xs text-text-tertiary uppercase tracking-wider">CMC Max</label>
                  <input type="number" min="0" max="20"
                    value={filters.cmc_max ?? ''}
                    onChange={e => updateFilter('cmc_max', e.target.value ? Number(e.target.value) : undefined)}
                    className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50"
                  />
                </div>
              </div>
              {/* Sort */}
              <div>
                <label className="text-xs text-text-tertiary uppercase tracking-wider">Sort By</label>
                <select
                  value={filters.sort_by || 'name'}
                  onChange={e => updateFilter('sort_by', e.target.value)}
                  className="mt-1 w-full px-3 py-2 bg-bg-tertiary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:border-accent-blue/50"
                >
                  <option value="name">Name</option>
                  <option value="cmc">CMC</option>
                  <option value="tcg_price">Price</option>
                  <option value="rarity">Rarity</option>
                  <option value="set_code">Set</option>
                  <option value="added_date">Date Added</option>
                </select>
              </div>
            </div>
          )}

          {/* Scanner */}
          <ScannerPanel onCardAdded={fetchCards} />
        </div>

        {/* Main content: card grid/list */}
        <div className="flex-1 min-w-0">
          {/* View toggle + pagination */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-1 bg-bg-secondary rounded-lg border border-border-primary p-0.5">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded-md transition-colors ${viewMode === 'grid' ? 'bg-bg-hover text-text-primary' : 'text-text-tertiary hover:text-text-secondary'}`}
              >
                <Grid3x3 className="w-4 h-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-1.5 rounded-md transition-colors ${viewMode === 'list' ? 'bg-bg-hover text-text-primary' : 'text-text-tertiary hover:text-text-secondary'}`}
              >
                <List className="w-4 h-4" />
              </button>
            </div>
            <div className="flex items-center gap-2 text-sm text-text-secondary">
              <span>Page {filters.page} of {totalPages || 1}</span>
              <button
                onClick={() => setFilters(p => ({ ...p, page: Math.max(1, (p.page || 1) - 1) }))}
                disabled={!filters.page || filters.page <= 1}
                className="p-1 rounded hover:bg-bg-hover disabled:opacity-30"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setFilters(p => ({ ...p, page: Math.min(totalPages, (p.page || 1) + 1) }))}
                disabled={(filters.page || 1) >= totalPages}
                className="p-1 rounded hover:bg-bg-hover disabled:opacity-30"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-64">
              <Spinner size="lg" className="text-accent-blue" />
            </div>
          ) : cards.length === 0 ? (
            <EmptyState
              icon={Package}
              title="No cards found"
              description="Try adjusting your search or filters, or import a collection."
            />
          ) : viewMode === 'grid' ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {cards.map(card => (
                <div
                  key={card.id}
                  className="group cursor-pointer"
                  onClick={() => setSelectedCard(card)}
                >
                  <CardImage src={card.image_url} alt={card.name} size="md" className="w-full h-auto aspect-[5/7]" />
                  <div className="mt-1.5 px-0.5">
                    <p className="text-xs font-medium text-text-primary truncate group-hover:text-accent-blue transition-colors">{card.name}</p>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-text-tertiary">{card.set_code.toUpperCase()}</span>
                      {card.tcg_price != null && (
                        <span className="text-[10px] text-accent-teal font-medium">${card.tcg_price.toFixed(2)}</span>
                      )}
                    </div>
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
                    <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Type</th>
                    <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Mana</th>
                    <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Set</th>
                    <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider">Qty</th>
                    <th className="px-4 py-3 text-xs text-text-tertiary font-medium uppercase tracking-wider text-right">Price</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-primary">
                  {cards.map(card => (
                    <tr key={card.id} className="hover:bg-bg-hover cursor-pointer transition-colors" onClick={() => setSelectedCard(card)}>
                      <td className="px-4 py-2.5">
                        <span className="font-medium text-text-primary">{card.name}</span>
                      </td>
                      <td className="px-4 py-2.5 text-text-secondary text-xs">{card.type_line}</td>
                      <td className="px-4 py-2.5"><ManaSymbols cost={card.mana_cost} /></td>
                      <td className="px-4 py-2.5 text-text-secondary text-xs">{card.set_code.toUpperCase()}</td>
                      <td className="px-4 py-2.5 text-text-secondary">{card.quantity}</td>
                      <td className="px-4 py-2.5 text-right text-accent-teal font-medium">{card.tcg_price != null ? `$${card.tcg_price.toFixed(2)}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Card detail modal */}
      {selectedCard && <CardDetailModal card={selectedCard} onClose={() => setSelectedCard(null)} />}
    </div>
  )
}
