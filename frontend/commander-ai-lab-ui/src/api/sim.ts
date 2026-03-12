import { get, post } from './client'
import type { SimStatus, SimResult, DeepSeekStatus } from '../types'

export async function runSim(config: { deck_a: string; deck_b: string; games: number }) {
  return post<{ sim_id: string }>('/api/sim/run', config)
}

export async function runSimFromDeck(deckId: number, config: { opponent?: string; games?: number }) {
  return post<{ sim_id: string }>('/api/sim/run-from-deck', { deck_id: deckId, ...config })
}

export async function runDeepSeekSim(config: { deck_a: string; deck_b: string; games: number; deepseek_deck: string }) {
  return post<{ sim_id: string }>('/api/sim/run-deepseek', config)
}

export async function getSimStatus(simId: string) {
  return get<SimStatus>('/api/sim/status', { simId })
}

export async function getSimResult(simId: string) {
  return get<SimResult>('/api/sim/result', { simId })
}

export async function connectDeepSeek() {
  return post<DeepSeekStatus>('/api/deepseek/connect')
}

export async function getDeepSeekStatus() {
  return get<DeepSeekStatus>('/api/deepseek/status')
}

export async function configureDeepSeek(config: { model?: string; base_url?: string }) {
  return post<DeepSeekStatus>('/api/deepseek/configure', config)
}

export async function getDeepSeekLogs() {
  return get<Array<{ filename: string; size: number; modified: string }>>('/api/deepseek/logs')
}
