import { get, post, put, del, patch } from './client'
import type { Deck, DeckCard, DeckAnalysis, DeckRecommendation, PplxStatus } from '../types'

export async function listDecks() {
  return get<Deck[]>('/api/decks')
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
  return get<DeckCard[]>(`/api/decks/${deckId}/cards`)
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
  return get<DeckAnalysis>(`/api/decks/${deckId}/analysis`)
}

export async function getCollectionRecs(deckId: number) {
  return get<DeckRecommendation[]>(`/api/decks/${deckId}/recommended-from-collection`)
}

export async function getEdhRecs(deckId: number) {
  return get<DeckRecommendation[]>(`/api/decks/${deckId}/edh-recs`)
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
