import { get, post } from './client'
import type { DeckGenV3Request, DeckGenV3Status, DeckGenV3Result, CommanderSearchResult } from '../types'

export async function getV3Status() {
  return get<DeckGenV3Status>('/api/deck/v3/status')
}

export async function searchCommanders(q: string) {
  return get<CommanderSearchResult[]>('/api/deck-generator/commander-search', { q })
}

export async function generateDeckV3(req: DeckGenV3Request) {
  return post<DeckGenV3Result>('/api/deck/v3/generate', req)
}

export async function commitDeckV3(req: DeckGenV3Request) {
  return post<DeckGenV3Result & { deck_id: number; dck_path: string }>('/api/deck/v3/commit', req)
}

export async function exportDeckV3(format: 'csv' | 'dck' | 'moxfield' | 'shopping', req: DeckGenV3Request) {
  return post<Record<string, unknown>>(`/api/deck/v3/export/${format}`, req)
}
