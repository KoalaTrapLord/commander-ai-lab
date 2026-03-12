import { get, post } from './client'
import type {
  MLStatus, MLDataStatus, MLTrainStatus, PPOTrainStatus,
  TournamentStatus, TournamentResults, MLModelInfo
} from '../types'

// ── ML Status & Toggle ──────────────────────────────────────
export async function getMLStatus() {
  return get<MLStatus>('/api/ml/status')
}

export async function toggleML(enable = true) {
  return post<{ ml_logging_enabled: boolean; message: string }>(`/api/ml/toggle?enable=${enable}`)
}

// ── Data & Model Info ───────────────────────────────────────
export async function getDataStatus() {
  return get<MLDataStatus>('/api/ml/data/status')
}

export async function getModelInfo() {
  return get<MLModelInfo>('/api/ml/model')
}

export async function reloadModel(checkpoint?: string) {
  return post<{ success: boolean; status: MLModelInfo }>('/api/ml/reload', checkpoint ? { checkpoint } : undefined)
}

// ── Supervised Training ─────────────────────────────────────
export async function startTraining(config: {
  epochs?: number
  lr?: number
  batchSize?: number
  patience?: number
  rebuildDataset?: boolean
}) {
  return post<{ status: string; config: Record<string, unknown> }>('/api/ml/train', config)
}

export async function getTrainStatus() {
  return get<MLTrainStatus>('/api/ml/train/status')
}

// ── PPO Training ────────────────────────────────────────────
export async function startPPOTraining(config: {
  iterations?: number
  episodesPerIter?: number
  ppoEpochs?: number
  batchSize?: number
  lr?: number
  clipEpsilon?: number
  entropyCoeff?: number
  opponent?: string
  playstyle?: string
  loadSupervised?: string
}) {
  return post<{ status: string; iterations: number }>('/api/ml/train/ppo', config)
}

export async function getPPOStatus() {
  return get<PPOTrainStatus>('/api/ml/train/ppo/status')
}

// ── Tournament ──────────────────────────────────────────────
export async function startTournament(config: {
  episodes?: number
  playstyle?: string
}) {
  return post<{ status: string; episodes: number }>('/api/ml/tournament', config)
}

export async function getTournamentStatus() {
  return get<TournamentStatus>('/api/ml/tournament/status')
}

export async function getTournamentResults() {
  return get<TournamentResults>('/api/ml/tournament/results')
}

// ── Decision Files ──────────────────────────────────────────
export async function getDecisionFile(filename: string, limit = 100, offset = 0) {
  return get<{ file: string; offset: number; limit: number; count: number; decisions: Record<string, unknown>[] }>(
    `/api/ml/decisions/${filename}?limit=${limit}&offset=${offset}`
  )
}

// ── Prediction ──────────────────────────────────────────────
export async function predict(state: Record<string, unknown>) {
  return post<{ action: string; action_index: number; confidence: number; probabilities: Record<string, number>; inference_ms: number }>(
    '/api/ml/predict', state
  )
}
