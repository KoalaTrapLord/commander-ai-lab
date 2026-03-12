import { get, post, put, del, patch } from './client'
import type { Deck, DeckCard, DeckAnalysis, EdhRecsResponse, CollectionRecsResponse, PplxStatus } from '../types'

export async function listDecks() {
  const res = await get<{ decks: Record<string, unknown>[] } | Record<string, unknown>[]>('/api/decks')
  const raw = Array.isArray(res) ? res : (res as { decks: Record<string, unknown>[] }).decks || []
  return raw.map(d => ({
    ...d,
    commander: d.commander || d.commander_name || '',
    card_count: d.card_count ?? d.total_cards ?? 0,
    total_price: d.total_price ?? 0,
    color_identity: d.color_identity || [],
    created_date: d.created_date || d.created_at || '',
    updated_date: d.updated_date || d.updated_at || '',
  })) as Deck[]
}

export async function getDeck(deckId: number) {
  return get<Deck>(`/api/decks/${deckId}`)
}

export async function createDeck(deck: { name: string; commander?: string; format?: string }) {
  return post<Deck>('/api/decks', deck)
}

export async function updateDeck(deckId: number, updates: Partial<Deck>) {
  return put<Deck>(`/api/decks/${deckId}`, updates)
}

export async function deleteDeck(deckId: number) {
  return del<void>(`/api/decks/${deckId}`)
}

export async function deleteAllDecks() {
  return del<void>('/api/decks')
}

export async function getDeckCards(deckId: number) {
  const res = await get<{ cards: Record<string, unknown>[]; total: number } | Record<string, unknown>[]>(`/api/decks/${deckId}/cards`)
  const raw = Array.isArray(res) ? res : (res as { cards: Record<string, unknown>[] }).cards || []
  return raw.map(c => ({
    ...c,
    name: c.name || c.card_name || '',
    category: c.category || c.role_tag || '',
  })) as DeckCard[]
}

export async function addCardToDeck(deckId: number, card: { name: string; scryfall_id?: string; quantity?: number; category?: string }) {
  return post<DeckCard>(`/api/decks/${deckId}/cards`, card)
}

export async function removeCardFromDeck(deckId: number, cardId: number) {
  return del<void>(`/api/decks/${deckId}/cards/${cardId}`)
}

export async function updateDeckCard(deckId: number, cardId: number, updates: Partial<DeckCard>) {
  return patch<DeckCard>(`/api/decks/${deckId}/cards/${cardId}`, updates)
}

export async function getDeckAnalysis(deckId: number) {
  const raw = await get<Record<string, unknown>>(`/api/decks/${deckId}/analysis`)
  // Backend returns: counts_by_type, targets, deltas, mana_curve, color_pips, total_cards, roles
  // Frontend DeckAnalysis expects: card_count, land_count, creature_count, noncreature_count, avg_cmc, mana_curve, color_distribution, type_distribution, total_price, owned_count, missing_count
  const counts = (raw.counts_by_type || {}) as Record<string, number>
  const totalCards = (raw.total_cards as number) || 0
  const landCount = counts['Land'] || 0
  const creatureCount = counts['Creature'] || 0
  const manaCurve = (raw.mana_curve || {}) as Record<string | number, number>
  const colorPips = (raw.color_pips || {}) as Record<string, number>
  // Compute avg CMC from mana curve
  let totalMana = 0, nonLandCards = 0
  for (const [cmc, count] of Object.entries(manaCurve)) {
    const cmcNum = cmc === '6+' ? 6 : Number(cmc)
    totalMana += cmcNum * count
    nonLandCards += count
  }
  return {
    card_count: totalCards,
    land_count: landCount,
    creature_count: creatureCount,
    noncreature_count: totalCards - landCount - creatureCount,
    avg_cmc: nonLandCards > 0 ? totalMana / nonLandCards : 0,
    mana_curve: manaCurve as Record<number, number>,
    color_distribution: colorPips,
    type_distribution: counts,
    total_price: 0,
    owned_count: totalCards,
    missing_count: 0,
  } as DeckAnalysis
}

export async function getCollectionRecs(deckId: number) {
  return get<CollectionRecsResponse>(`/api/decks/${deckId}/recommended-from-collection`)
}

export async function getEdhRecs(deckId: number, onlyOwned = false, maxResults = 30) {
  return get<EdhRecsResponse>(`/api/decks/${deckId}/edh-recs?only_owned=${onlyOwned}&max_results=${maxResults}`)
}

export async function bulkAddCards(deckId: number, cards: { name: string; quantity?: number }[]) {
  return post<{ added: number }>(`/api/decks/${deckId}/bulk-add`, { cards })
}

export async function bulkAddRecommended(deckId: number, cards: string[]) {
  return post<{ added: number }>(`/api/decks/${deckId}/bulk-add-recommended`, { card_names: cards })
}

export async function exportDeckToSim(deckId: number) {
  return post<{ path: string }>(`/api/decks/${deckId}/export-to-sim`)
}

export async function importDeckToDeck(deckId: number, data: { text?: string; url?: string }) {
  return post<{ imported: number }>(`/api/decks/${deckId}/import`, data)
}

export async function importNewDeck(data: { text?: string; url?: string; name?: string }) {
  return post<Deck>('/api/decks/import-new', data)
}

export async function getPplxStatus() {
  return get<PplxStatus>('/api/pplx/status')
}

export async function deckResearch(payload: { commander: string; strategy?: string }) {
  return post<{ research: string }>('/api/deck-research', payload)
}

export async function deckGenerate(payload: { commander: string; strategy?: string; bracket?: number }) {
  return post<{ cards: Array<{ name: string; quantity: number; category: string }> }>('/api/deck-generate', payload)
}
