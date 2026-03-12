import { get, post } from './client'
import type {
  CoachStatus, CoachDeck, CoachSession, CoachSessionSummary,
  CoachChatResponse, CoachApplyResult, CoachCardLikeResult
} from '../types'

export async function getCoachStatus() {
  return get<CoachStatus>('/api/coach/status')
}

export async function getCoachDecks() {
  return get<CoachDeck[]>('/api/coach/decks')
}

export async function getCoachDeckReport(deckId: string) {
  return get<Record<string, unknown>>(`/api/coach/decks/${deckId}/report`)
}

export async function runCoachSession(deckId: string, goals?: Record<string, unknown>) {
  return post<CoachSession>(`/api/coach/decks/${deckId}`, goals ? { goals } : undefined)
}

export async function getCoachSessions(deckId?: string) {
  const params: Record<string, string> = {}
  if (deckId) params.deck_id = deckId
  return get<{ sessions: CoachSessionSummary[] }>('/api/coach/sessions', params)
}

export async function getCoachSession(sessionId: string) {
  return get<CoachSession>(`/api/coach/sessions/${sessionId}`)
}

export async function downloadEmbeddings() {
  return post<{ success: boolean; cards: number }>('/api/coach/embeddings/download')
}

export async function coachChat(
  deckId: string,
  messages: { role: string; content: string }[],
  goals?: Record<string, unknown>
) {
  return post<CoachChatResponse>('/api/coach/chat', {
    deck_id: deckId,
    messages,
    goals,
    stream: false,
  })
}

export async function coachChatStream(
  deckId: string,
  messages: { role: string; content: string }[],
  goals?: Record<string, unknown>,
  onChunk?: (text: string) => void,
  signal?: AbortSignal
): Promise<string> {
  const res = await fetch('/api/coach/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      deck_id: deckId,
      messages,
      goals,
      stream: true,
    }),
    signal,
  })

  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `HTTP ${res.status}`)
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let fullText = ''
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        if (data === '[DONE]') break
        try {
          const parsed = JSON.parse(data)
          if (parsed.content) {
            fullText += parsed.content
            onChunk?.(fullText)
          }
        } catch { /* skip bad chunks */ }
      }
    }
  }

  return fullText
}

export async function applyCoachSuggestions(
  sessionId: string,
  deckId: number,
  acceptedCuts: string[],
  acceptedAdds: string[]
) {
  return post<CoachApplyResult>('/api/coach/apply', {
    session_id: sessionId,
    deck_id: deckId,
    accepted_cuts: acceptedCuts,
    accepted_adds: acceptedAdds,
  })
}

export async function searchCardsLike(card: string, colors?: string, topN = 10) {
  const params: Record<string, string | number> = { card, top_n: topN }
  if (colors) params.colors = colors
  return get<{ query: string; results: CoachCardLikeResult[] }>('/api/coach/cards-like', params)
}

export async function generateReport(deckId?: number) {
  return post<{ status: string; decksUpdated: string[]; count: number }>('/api/coach/reports/generate',
    deckId ? { deck_id: deckId } : undefined
  )
}
