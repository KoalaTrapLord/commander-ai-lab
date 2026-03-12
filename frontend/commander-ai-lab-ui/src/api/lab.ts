import { get, post } from './client'
import type { LabDeck, LabStatus, LabResult, LabHistoryEntry, PreconDeck } from '../types'

export async function getLabDecks() {
  const res = await get<{ decks: LabDeck[] } | LabDeck[]>('/api/lab/decks')
  return Array.isArray(res) ? res : (res as { decks: LabDeck[] }).decks || []
}

export async function startBatchSim(config: { decks: string[]; games: number; threads?: number; use_deepseek?: boolean; deepseek_deck?: string }) {
  return post<{ run_id: string }>('/api/lab/start', config)
}

export async function startDeepSeekSim(config: { decks: string[]; games: number; deepseek_deck: string }) {
  return post<{ run_id: string }>('/api/lab/start-deepseek', config)
}

export async function getLabStatus() {
  return get<LabStatus>('/api/lab/status')
}

export async function getLabResult() {
  return get<LabResult>('/api/lab/result')
}

export async function getLabHistory() {
  const res = await get<{ results: LabHistoryEntry[] } | LabHistoryEntry[]>('/api/lab/history')
  return Array.isArray(res) ? res : (res as { results: LabHistoryEntry[] }).results || []
}

export async function getPrecons() {
  const res = await get<{ precons: PreconDeck[] } | PreconDeck[]>('/api/lab/precons')
  return Array.isArray(res) ? res : (res as { precons: PreconDeck[] }).precons || []
}

export async function installPrecon(name: string) {
  return post<{ installed: boolean }>('/api/lab/precons/install', { name })
}

export async function installPreconBatch(names: string[]) {
  return post<{ installed: number }>('/api/lab/precons/install-batch', { names })
}

export async function getMetaCommanders() {
  return get<Array<{ name: string; color_identity: string[] }>>('/api/lab/meta/commanders')
}

export async function searchMetaCommanders(q: string) {
  return get<Array<{ name: string; color_identity: string[]; source: string }>>('/api/lab/meta/search', { q })
}

export async function fetchMetaDeck(commander: string) {
  return post<{ deck_name: string; cards: Array<{ name: string; quantity: number }> }>('/api/lab/meta/fetch', { commander })
}

export async function importDeckFromUrl(url: string) {
  return post<{ deck_name: string }>('/api/lab/import/url', { url })
}

export async function importDeckFromText(text: string, name?: string) {
  return post<{ deck_name: string }>('/api/lab/import/text', { text, name })
}

export async function getLabLog() {
  return get<{ log: string }>('/api/lab/log')
}
