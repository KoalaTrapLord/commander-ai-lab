import { useState, useEffect, useRef } from 'react'
import {
  GraduationCap, MessageSquare, Download,
  ChevronRight, Sparkles, AlertCircle, X
} from 'lucide-react'
import { Spinner, StatusBadge, EmptyState } from '../components/common'
import { coachApi } from '../api'
import type { CoachStatus, CoachDeck, CoachSession } from '../types'

// ── Chat Session View ─────────────────────────────────────────
function ChatView({ session, onClose }: { session: CoachSession; onClose: () => void }) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [session.messages])

  return (
    <div className="flex flex-col h-[calc(100vh-160px)]">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border-primary">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{session.deck_name}</h3>
          <p className="text-xs text-text-tertiary">{new Date(session.created_at).toLocaleString()}</p>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-bg-hover text-text-tertiary">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {session.messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] px-4 py-3 rounded-xl text-sm whitespace-pre-wrap leading-relaxed ${
              msg.role === 'user'
                ? 'bg-accent-blue/15 text-text-primary border border-accent-blue/20'
                : 'bg-bg-tertiary text-text-primary border border-border-primary'
            }`}>
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
    </div>
  )
}

// ── Main Coach Page ───────────────────────────────────────────
export function CoachPage() {
  const [status, setStatus] = useState<CoachStatus | null>(null)
  const [decks, setDecks] = useState<CoachDeck[]>([])
  const [sessions, setSessions] = useState<CoachSession[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedSession, setSelectedSession] = useState<CoachSession | null>(null)
  const [generatingReport, setGeneratingReport] = useState<number | null>(null)
  const [downloadingEmbeddings, setDownloadingEmbeddings] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [s, d, sess] = await Promise.all([
          coachApi.getCoachStatus(),
          coachApi.getCoachDecks(),
          coachApi.getCoachSessions(),
        ])
        setStatus(s)
        setDecks(d)
        setSessions(sess)
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [])

  async function handleGenerateReport(deckId: number) {
    setGeneratingReport(deckId)
    setError(null)
    try {
      await coachApi.generateReport(deckId)
      // Refresh decks
      const d = await coachApi.getCoachDecks()
      setDecks(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Report generation failed')
    }
    setGeneratingReport(null)
  }

  async function handleDownloadEmbeddings() {
    setDownloadingEmbeddings(true)
    try {
      await coachApi.downloadEmbeddings()
      const s = await coachApi.getCoachStatus()
      setStatus(s)
    } catch { /* ignore */ }
    setDownloadingEmbeddings(false)
  }

  async function viewSession(sessionId: string) {
    try {
      const s = await coachApi.getCoachSession(sessionId)
      setSelectedSession(s)
    } catch { /* ignore */ }
  }

  if (loading) {
    return <div className="p-6 flex items-center justify-center h-64"><Spinner size="lg" className="text-accent-blue" /></div>
  }

  if (selectedSession) {
    return (
      <div className="p-6">
        <ChatView session={selectedSession} onClose={() => setSelectedSession(null)} />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
          <GraduationCap className="w-6 h-6 text-accent-amber" />
          Deck Coach
        </h1>
        <p className="text-sm text-text-secondary mt-0.5">AI-powered deck analysis and coaching</p>
      </div>

      {/* Status */}
      <div className="flex items-center gap-3">
        <StatusBadge
          variant={status?.llm_connected ? 'success' : 'warning'}
          label={status?.llm_connected ? `LLM: ${status.active_model}` : 'LLM: Disconnected'}
        />
        <StatusBadge
          variant={status?.embeddings_loaded ? 'success' : 'neutral'}
          label={status?.embeddings_loaded ? `${status.embedding_cards.toLocaleString()} embeddings` : 'No embeddings'}
        />
        {!status?.embeddings_loaded && (
          <button onClick={handleDownloadEmbeddings} disabled={downloadingEmbeddings}
            className="flex items-center gap-1.5 text-xs text-accent-blue hover:text-accent-blue-hover transition-colors">
            {downloadingEmbeddings ? <Spinner size="sm" /> : <Download className="w-3 h-3" />}
            Download Embeddings
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-status-error/10 border border-status-error/30 rounded-lg text-sm text-status-error">
          <AlertCircle className="w-4 h-4" />{error}
        </div>
      )}

      {/* Decks for coaching */}
      <div>
        <h2 className="text-lg font-semibold text-text-primary mb-3">Your Decks</h2>
        {decks.length === 0 ? (
          <EmptyState icon={GraduationCap} title="No decks available" description="Create decks in the Deck Builder to use the coach." />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {decks.map(deck => (
              <div key={deck.deck_id} className="bg-bg-secondary rounded-xl border border-border-primary p-5 space-y-3">
                <div>
                  <h3 className="text-base font-semibold text-text-primary">{deck.deck_name}</h3>
                  <p className="text-sm text-text-secondary">{deck.commander}</p>
                </div>
                <div className="flex items-center gap-3 text-xs text-text-tertiary">
                  <span>{deck.report_count} reports</span>
                  {deck.last_report_date && <span>Last: {new Date(deck.last_report_date).toLocaleDateString()}</span>}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleGenerateReport(deck.deck_id)}
                    disabled={generatingReport === deck.deck_id}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-accent-amber/15 text-accent-amber text-xs font-medium rounded-lg hover:bg-accent-amber/25 border border-accent-amber/30 transition-colors disabled:opacity-50"
                  >
                    {generatingReport === deck.deck_id ? <Spinner size="sm" /> : <Sparkles className="w-3.5 h-3.5" />}
                    Generate Report
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sessions */}
      <div>
        <button onClick={() => setShowSessions(!showSessions)}
          className="flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary transition-colors">
          <MessageSquare className="w-4 h-4" />
          Coaching Sessions ({sessions.length})
          <ChevronRight className={`w-3.5 h-3.5 transition-transform ${showSessions ? 'rotate-90' : ''}`} />
        </button>
        {showSessions && sessions.length > 0 && (
          <div className="mt-3 space-y-2 animate-fade-in">
            {sessions.map(s => (
              <button
                key={s.session_id}
                onClick={() => viewSession(s.session_id)}
                className="w-full flex items-center gap-4 px-4 py-3 bg-bg-secondary rounded-lg border border-border-primary hover:border-border-secondary text-left transition-colors"
              >
                <MessageSquare className="w-4 h-4 text-text-tertiary" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-text-primary">{s.deck_name}</p>
                  <p className="text-xs text-text-tertiary">{new Date(s.created_at).toLocaleString()} · {s.messages.length} messages</p>
                </div>
                <ChevronRight className="w-4 h-4 text-text-tertiary" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
