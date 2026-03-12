import { get, post } from './client'
import type { CoachStatus, CoachDeck, CoachSession } from '../types'

export async function getCoachStatus() {
  return get<CoachStatus>('/api/coach/status')
}

export async function getCoachDecks() {
  return get<CoachDeck[]>('/api/coach/decks')
}

export async function getCoachDeckReport(deckId: number) {
  return get<Record<string, unknown>>(`/api/coach/decks/${deckId}/report`)
}

export async function analyzeCoachDeck(deckId: number) {
  return post<Record<string, unknown>>(`/api/coach/decks/${deckId}`)
}

export async function getCoachSessions() {
  return get<CoachSession[]>('/api/coach/sessions')
}

export async function getCoachSession(sessionId: string) {
  return get<CoachSession>(`/api/coach/sessions/${sessionId}`)
}

export async function downloadEmbeddings() {
  return post<{ status: string }>('/api/coach/embeddings/download')
}

export async function searchEmbeddings(q: string, topK?: number) {
  return get<Array<{ name: string; score: number }>>('/api/coach/embeddings/search', { q, top_k: topK })
}

export async function generateReport(deckId: number) {
  return post<{ report_id: string }>('/api/coach/reports/generate', { deck_id: deckId })
}
