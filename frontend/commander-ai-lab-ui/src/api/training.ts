import { get, post } from './client'
import type { MLStatus, MLDataStatus, MLTrainStatus, PPOTrainStatus, TournamentStatus, TournamentResults } from '../types'

export async function getMLStatus() {
  return get<MLStatus>('/api/ml/status')
}

export async function toggleML() {
  return post<{ enabled: boolean }>('/api/ml/toggle')
}

export async function getDecisionFile(filename: string) {
  return get<Record<string, unknown>>(`/api/ml/decisions/${filename}`)
}

export async function predict(state: Record<string, unknown>) {
  return post<{ action: string; confidence: number }>('/api/ml/predict', state)
}

export async function reloadModel() {
  return post<{ loaded: boolean }>('/api/ml/reload')
}

export async function getModelInfo() {
  return get<Record<string, unknown>>('/api/ml/model')
}

export async function startTraining(config?: { epochs?: number; lr?: number }) {
  return post<{ started: boolean }>('/api/ml/train', config)
}

export async function getTrainStatus() {
  return get<MLTrainStatus>('/api/ml/train/status')
}

export async function getDataStatus() {
  return get<MLDataStatus>('/api/ml/data/status')
}

export async function startPPOTraining(config?: { iterations?: number }) {
  return post<{ started: boolean }>('/api/ml/train/ppo', config)
}

export async function getPPOStatus() {
  return get<PPOTrainStatus>('/api/ml/train/ppo/status')
}

export async function startTournament(config?: { games?: number }) {
  return post<{ started: boolean }>('/api/ml/tournament', config)
}

export async function getTournamentStatus() {
  return get<TournamentStatus>('/api/ml/tournament/status')
}

export async function getTournamentResults() {
  return get<TournamentResults>('/api/ml/tournament/results')
}
