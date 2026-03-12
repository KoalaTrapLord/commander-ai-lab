import { get, post, patch, postForm } from './client'
import type { CollectionCard, CollectionFilters, SetInfo, ScanResult } from '../types'

export async function searchCollection(filters: CollectionFilters) {
  // Map frontend snake_case filter names to backend camelCase param names
  const params: Record<string, string | number | boolean> = {}
  if (filters.q) params.q = filters.q
  if (filters.page) params.page = filters.page
  if (filters.page_size) params.pageSize = filters.page_size
  if (filters.sort_by) params.sortField = filters.sort_by
  if (filters.sort_dir) params.sortDir = filters.sort_dir
  if (filters.color) params.colors = filters.color
  if (filters.type_line) params.types = filters.type_line
  if (filters.rarity) params.rarity = filters.rarity
  if (filters.set_code) params.setCode = filters.set_code
  if (filters.cmc_min !== undefined) params.cmcMin = filters.cmc_min
  if (filters.cmc_max !== undefined) params.cmcMax = filters.cmc_max
  if (filters.price_min !== undefined) params.priceMin = filters.price_min
  if (filters.price_max !== undefined) params.priceMax = filters.price_max
  if (filters.owned_only !== undefined) params.owned_only = filters.owned_only

  const res = await get<{ items?: CollectionCard[]; cards?: CollectionCard[]; total: number; page: number; pageSize?: number; page_size?: number }>(
    '/api/collection', params
  )
  return {
    cards: res.items || res.cards || [],
    total: res.total || 0,
    page: res.page || 1,
    page_size: res.pageSize || res.page_size || 48,
  }
}

export async function getCard(cardId: number) {
  return get<CollectionCard>(`/api/collection/${cardId}`)
}

export async function updateCard(cardId: number, updates: Partial<CollectionCard>) {
  return patch<CollectionCard>(`/api/collection/${cardId}`, updates)
}

export async function getSets() {
  const res = await get<SetInfo[] | { sets: SetInfo[] }>('/api/collection/sets')
  return Array.isArray(res) ? res : (res as { sets: SetInfo[] }).sets || []
}

export async function getKeywords() {
  const res = await get<string[] | { keywords: string[] }>('/api/collection/keywords')
  return Array.isArray(res) ? res : (res as { keywords: string[] }).keywords || []
}

export async function exportCollection(format: string = 'csv') {
  const res = await fetch(`/api/collection/export?format=${format}`)
  return res.blob()
}

export async function importCollection(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return postForm<{ imported: number; errors: string[] }>('/api/collection/import', fd)
}

export async function scanCard(file: File) {
  const fd = new FormData()
  fd.append('image', file)
  return postForm<ScanResult>('/api/collection/scan', fd)
}

export async function addScanResult(match: { name: string; set_code: string; scryfall_id: string; quantity?: number }) {
  return post<{ success: boolean; card_id: number }>('/api/collection/scan/add', match)
}

export async function reEnrichCards() {
  return post<{ updated: number }>('/api/collection/re-enrich')
}

export async function autoClassify(cardId: number) {
  return post<{ classifications: string[] }>(`/api/collection/auto-classify`, { card_id: cardId })
}

export async function autoClassifyAll() {
  return post<{ processed: number }>('/api/collection/auto-classify-all')
}

export async function getEdhrecData(cardId: number) {
  return get<Record<string, unknown>>(`/api/collection/${cardId}/edhrec`)
}
