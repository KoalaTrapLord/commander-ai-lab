import { get, post, patch, postForm } from './client'
import type { CollectionCard, CollectionFilters, SetInfo, ScanResult } from '../types'

export async function searchCollection(filters: CollectionFilters) {
  return get<{ cards: CollectionCard[]; total: number; page: number; page_size: number }>(
    '/api/collection', filters as Record<string, string | number | boolean>
  )
}

export async function getCard(cardId: number) {
  return get<CollectionCard>(`/api/collection/${cardId}`)
}

export async function updateCard(cardId: number, updates: Partial<CollectionCard>) {
  return patch<CollectionCard>(`/api/collection/${cardId}`, updates)
}

export async function getSets() {
  return get<SetInfo[]>('/api/collection/sets')
}

export async function getKeywords() {
  return get<string[]>('/api/collection/keywords')
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
