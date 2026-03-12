import { useState, useEffect, useRef, useCallback } from 'react'
import {
  GraduationCap, MessageSquare, Send, Sparkles, AlertCircle, X, Check,
  ChevronRight, ChevronDown, Download, Settings2, Search, Zap,
  Minus, Plus, History, ArrowRightLeft, Lightbulb, DollarSign, Loader2,
  ClipboardList, Brain, BarChart3
} from 'lucide-react'
import { Spinner, StatusBadge, EmptyState } from '../components/common'
import { coachApi } from '../api'
import type {
  CoachStatus, CoachDeck, CoachSession, CoachSessionSummary,
  CoachMessage, CoachGoals, CoachApplyResult, CoachCardLikeResult
} from '../types'

// ════════════════════════════════════════════════════════════
// Goals Config Panel
// ════════════════════════════════════════════════════════════
function GoalsPanel({
  goals, onChange, collapsed, onToggle
}: {
  goals: CoachGoals
  onChange: (g: CoachGoals) => void
  collapsed: boolean
  onToggle: () => void
}) {
  const strategies = ['aggro', 'control', 'combo', 'midrange', 'stax', 'voltron', 'aristocrats', 'tokens']
  const budgets = [
    { value: 'budget', label: 'Budget', desc: 'Under $5/card' },
    { value: 'medium', label: 'Medium', desc: 'Under $20/card' },
    { value: 'no-limit', label: 'No Limit', desc: 'Any price' },
  ]
  const focusOptions = ['ramp', 'card draw', 'removal', 'protection', 'threats', 'mana base', 'combos', 'synergy']

  return (
    <div className="bg-bg-secondary rounded-xl border border-border-primary">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-bg-hover transition-colors rounded-xl"
      >
        <Settings2 className="w-4 h-4 text-accent-teal" />
        <span className="text-sm font-medium text-text-primary flex-1">Coaching Goals</span>
        {collapsed ? <ChevronRight className="w-4 h-4 text-text-tertiary" /> : <ChevronDown className="w-4 h-4 text-text-tertiary" />}
      </button>

      {!collapsed && (
        <div className="px-4 pb-4 space-y-4 border-t border-border-primary pt-3">
          {/* Power Level Slider */}
          <div>
            <label className="text-xs font-medium text-text-secondary mb-1 block">
              Power Level: {goals.targetPowerLevel ?? 'Any'}
            </label>
            <input
              type="range" min={1} max={10}
              value={goals.targetPowerLevel ?? 5}
              onChange={e => onChange({ ...goals, targetPowerLevel: parseInt(e.target.value) })}
              className="w-full accent-accent-teal"
            />
            <div className="flex justify-between text-[10px] text-text-tertiary">
              <span>Casual</span><span>Focused</span><span>cEDH</span>
            </div>
          </div>

          {/* Strategy */}
          <div>
            <label className="text-xs font-medium text-text-secondary mb-1.5 block">Strategy Focus</label>
            <div className="flex flex-wrap gap-1.5">
              {strategies.map(s => (
                <button
                  key={s}
                  onClick={() => onChange({ ...goals, metaFocus: goals.metaFocus === s ? null : s })}
                  className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                    goals.metaFocus === s
                      ? 'bg-accent-teal/20 border-accent-teal/40 text-accent-teal'
                      : 'border-border-primary text-text-tertiary hover:border-border-secondary'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Budget */}
          <div>
            <label className="text-xs font-medium text-text-secondary mb-1.5 block">Budget</label>
            <div className="grid grid-cols-3 gap-2">
              {budgets.map(b => (
                <button
                  key={b.value}
                  onClick={() => onChange({ ...goals, budget: goals.budget === b.value ? null : b.value })}
                  className={`px-3 py-2 text-xs rounded-lg border transition-colors ${
                    goals.budget === b.value
                      ? 'bg-accent-teal/20 border-accent-teal/40 text-accent-teal'
                      : 'border-border-primary text-text-tertiary hover:border-border-secondary'
                  }`}
                >
                  <div className="font-medium">{b.label}</div>
                  <div className="text-[10px] opacity-60">{b.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Focus Areas */}
          <div>
            <label className="text-xs font-medium text-text-secondary mb-1.5 block">Focus Areas</label>
            <div className="flex flex-wrap gap-1.5">
              {focusOptions.map(f => {
                const active = (goals.focusAreas || []).includes(f)
                return (
                  <button
                    key={f}
                    onClick={() => {
                      const areas = goals.focusAreas || []
                      onChange({
                        ...goals,
                        focusAreas: active ? areas.filter(a => a !== f) : [...areas, f]
                      })
                    }}
                    className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                      active
                        ? 'bg-accent-blue/20 border-accent-blue/40 text-accent-blue'
                        : 'border-border-primary text-text-tertiary hover:border-border-secondary'
                    }`}
                  >
                    {f}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// Session View — Shows coaching results with apply functionality
// ════════════════════════════════════════════════════════════
function SessionView({
  session, deckId, onClose, onApplied
}: {
  session: CoachSession
  deckId: number
  onClose: () => void
  onApplied?: () => void
}) {
  const [selectedCuts, setSelectedCuts] = useState<Set<string>>(new Set())
  const [selectedAdds, setSelectedAdds] = useState<Set<string>>(new Set())
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState<CoachApplyResult | null>(null)

  const toggleCut = (name: string) => {
    const s = new Set(selectedCuts)
    s.has(name) ? s.delete(name) : s.add(name)
    setSelectedCuts(s)
  }
  const toggleAdd = (name: string) => {
    const s = new Set(selectedAdds)
    s.has(name) ? s.delete(name) : s.add(name)
    setSelectedAdds(s)
  }

  const handleApply = async () => {
    if (selectedCuts.size === 0 && selectedAdds.size === 0) return
    setApplying(true)
    try {
      const result = await coachApi.applyCoachSuggestions(
        session.sessionId, deckId,
        [...selectedCuts], [...selectedAdds]
      )
      setApplyResult(result)
      onApplied?.()
    } catch (e) {
      console.error('Apply failed:', e)
    }
    setApplying(false)
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-text-primary">Coaching Session</h3>
          <p className="text-xs text-text-tertiary">
            {new Date(session.timestamp).toLocaleString()} · {session.modelUsed}
            {session.promptTokens > 0 && ` · ${session.promptTokens + session.completionTokens} tokens`}
          </p>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-bg-hover text-text-tertiary">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Summary */}
      {session.summary && (
        <div className="bg-bg-secondary rounded-xl border border-border-primary p-4">
          <h4 className="text-xs font-medium text-text-secondary mb-2 flex items-center gap-1.5">
            <Brain className="w-3.5 h-3.5" /> Summary
          </h4>
          <p className="text-sm text-text-primary leading-relaxed">{session.summary}</p>
        </div>
      )}

      {/* Heuristic Hints */}
      {session.heuristicHints?.length > 0 && (
        <div className="bg-accent-amber/5 rounded-xl border border-accent-amber/20 p-4">
          <h4 className="text-xs font-medium text-accent-amber mb-2 flex items-center gap-1.5">
            <Lightbulb className="w-3.5 h-3.5" /> Strategic Tips
          </h4>
          <ul className="space-y-1.5">
            {session.heuristicHints.map((h, i) => (
              <li key={i} className="text-sm text-text-primary flex items-start gap-2">
                <span className="text-accent-amber mt-0.5">•</span> {h}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Mana Base Advice */}
      {session.manaBaseAdvice && (
        <div className="bg-accent-blue/5 rounded-xl border border-accent-blue/20 p-4">
          <h4 className="text-xs font-medium text-accent-blue mb-2 flex items-center gap-1.5">
            <BarChart3 className="w-3.5 h-3.5" /> Mana Base
          </h4>
          <p className="text-sm text-text-primary">{session.manaBaseAdvice}</p>
        </div>
      )}

      {/* Suggested Cuts */}
      {session.suggestedCuts?.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-status-error mb-2 flex items-center gap-1.5">
            <Minus className="w-4 h-4" /> Suggested Cuts ({session.suggestedCuts.length})
          </h4>
          <div className="space-y-2">
            {session.suggestedCuts.map((cut, i) => (
              <div
                key={i}
                onClick={() => toggleCut(cut.cardName)}
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedCuts.has(cut.cardName)
                    ? 'bg-status-error/10 border-status-error/30'
                    : 'bg-bg-secondary border-border-primary hover:border-border-secondary'
                }`}
              >
                <div className={`mt-0.5 w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${
                  selectedCuts.has(cut.cardName)
                    ? 'bg-status-error border-status-error text-white'
                    : 'border-border-secondary'
                }`}>
                  {selectedCuts.has(cut.cardName) && <Check className="w-3 h-3" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-text-primary">{cut.cardName}</p>
                  <p className="text-xs text-text-secondary mt-0.5">{cut.reason}</p>
                  {cut.replacementOptions?.length > 0 && (
                    <p className="text-[10px] text-text-tertiary mt-1">
                      Replace with: {cut.replacementOptions.join(', ')}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Suggested Adds */}
      {session.suggestedAdds?.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-status-success mb-2 flex items-center gap-1.5">
            <Plus className="w-4 h-4" /> Suggested Adds ({session.suggestedAdds.length})
          </h4>
          <div className="space-y-2">
            {session.suggestedAdds.map((add, i) => (
              <div
                key={i}
                onClick={() => toggleAdd(add.cardName)}
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedAdds.has(add.cardName)
                    ? 'bg-status-success/10 border-status-success/30'
                    : 'bg-bg-secondary border-border-primary hover:border-border-secondary'
                }`}
              >
                <div className={`mt-0.5 w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${
                  selectedAdds.has(add.cardName)
                    ? 'bg-status-success border-status-success text-white'
                    : 'border-border-secondary'
                }`}>
                  {selectedAdds.has(add.cardName) && <Check className="w-3 h-3" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-text-primary">{add.cardName}</p>
                    {add.role && (
                      <span className="px-1.5 py-0.5 text-[10px] bg-accent-blue/15 text-accent-blue rounded">
                        {add.role}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-text-secondary mt-0.5">{add.reason}</p>
                  {add.synergyWith?.length > 0 && (
                    <p className="text-[10px] text-text-tertiary mt-1">
                      Synergy: {add.synergyWith.join(', ')}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Apply Button */}
      {!applyResult && (selectedCuts.size > 0 || selectedAdds.size > 0) && (
        <div className="sticky bottom-0 bg-bg-primary/95 backdrop-blur-sm border-t border-border-primary py-3 -mx-6 px-6">
          <button
            onClick={handleApply}
            disabled={applying}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent-blue text-white text-sm font-medium rounded-lg hover:bg-accent-blue-hover transition-colors disabled:opacity-50"
          >
            {applying ? <Spinner size="sm" /> : <ArrowRightLeft className="w-4 h-4" />}
            Apply {selectedCuts.size > 0 && `${selectedCuts.size} cuts`}
            {selectedCuts.size > 0 && selectedAdds.size > 0 && ' + '}
            {selectedAdds.size > 0 && `${selectedAdds.size} adds`} to Deck
          </button>
        </div>
      )}

      {/* Apply Results */}
      {applyResult && (
        <div className="bg-status-success/5 rounded-xl border border-status-success/20 p-4">
          <h4 className="text-sm font-medium text-status-success mb-2 flex items-center gap-1.5">
            <Check className="w-4 h-4" /> Changes Applied
          </h4>
          <p className="text-sm text-text-primary">
            {applyResult.total_cuts > 0 && `Removed ${applyResult.total_cuts} card(s). `}
            {applyResult.total_adds > 0 && `Added ${applyResult.total_adds} card(s). `}
            {applyResult.errors.length > 0 && `${applyResult.errors.length} error(s).`}
          </p>
          {applyResult.errors.length > 0 && (
            <ul className="mt-2 text-xs text-status-error">
              {applyResult.errors.map((e, i) => (
                <li key={i}>{e.name}: {e.error}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Raw Explanation */}
      {session.rawTextExplanation && (
        <details className="group">
          <summary className="text-xs text-text-tertiary cursor-pointer hover:text-text-secondary">
            Full analysis...
          </summary>
          <p className="mt-2 text-sm text-text-secondary whitespace-pre-wrap leading-relaxed bg-bg-secondary rounded-lg p-4 border border-border-primary">
            {session.rawTextExplanation}
          </p>
        </details>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// Cards Like Search
// ════════════════════════════════════════════════════════════
function CardsLikePanel() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CoachCardLikeResult[]>([])
  const [searching, setSearching] = useState(false)

  const handleSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const data = await coachApi.searchCardsLike(query.trim(), undefined, 12)
      setResults(data.results)
    } catch { /* ignore */ }
    setSearching(false)
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="Enter a card name..."
            className="w-full pl-9 pr-3 py-2 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={searching || !query.trim()}
          className="px-4 py-2 bg-accent-teal/15 text-accent-teal text-sm font-medium rounded-lg hover:bg-accent-teal/25 border border-accent-teal/30 transition-colors disabled:opacity-50"
        >
          {searching ? <Spinner size="sm" /> : 'Search'}
        </button>
      </div>

      {results.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {results.map((card, i) => (
            <div key={i} className="flex items-start gap-3 p-3 bg-bg-secondary rounded-lg border border-border-primary">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-text-primary truncate">{card.name}</p>
                  <span className="text-[10px] text-text-tertiary whitespace-nowrap">
                    {(card.similarity * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-[11px] text-text-secondary mt-0.5">{card.types}</p>
                {card.text && (
                  <p className="text-[10px] text-text-tertiary mt-1 line-clamp-2">{card.text}</p>
                )}
                <div className="flex items-center gap-3 mt-1.5 text-[10px]">
                  {card.tcg_price != null && (
                    <span className="text-accent-amber flex items-center gap-0.5">
                      <DollarSign className="w-2.5 h-2.5" />{card.tcg_price.toFixed(2)}
                    </span>
                  )}
                  {card.owned_qty > 0 && (
                    <span className="text-status-success">Owned: {card.owned_qty}</span>
                  )}
                  <span className="text-text-tertiary">MV: {card.mana_value}</span>
                </div>
              </div>
              {card.image_url && (
                <img src={card.image_url} alt={card.name} className="w-14 h-auto rounded" />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// Live Chat View
// ════════════════════════════════════════════════════════════
function LiveChat({
  deckId, deckName, goals, onClose
}: {
  deckId: string
  deckName: string
  goals: CoachGoals
  onClose: () => void
}) {
  const [messages, setMessages] = useState<CoachMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamText, setStreamText] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamText])

  const sendMessage = async () => {
    if (!input.trim() || streaming) return
    const userMsg: CoachMessage = { role: 'user', content: input.trim() }
    const allMessages = [...messages, userMsg]
    setMessages(allMessages)
    setInput('')
    setStreaming(true)
    setStreamText('')

    const goalsDict = goals.targetPowerLevel || goals.metaFocus || goals.budget || (goals.focusAreas || []).length > 0
      ? {
          targetPowerLevel: goals.targetPowerLevel,
          metaFocus: goals.metaFocus,
          budget: goals.budget,
          focusAreas: goals.focusAreas,
        }
      : undefined

    try {
      abortRef.current = new AbortController()
      const fullText = await coachApi.coachChatStream(
        deckId,
        allMessages.map(m => ({ role: m.role, content: m.content })),
        goalsDict,
        (text) => setStreamText(text),
        abortRef.current.signal
      )

      setMessages(prev => [...prev, { role: 'assistant', content: fullText }])
      setStreamText('')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        // Fallback to non-streaming
        try {
          const resp = await coachApi.coachChat(
            deckId,
            allMessages.map(m => ({ role: m.role, content: m.content })),
            goalsDict
          )
          setMessages(prev => [...prev, { role: 'assistant', content: resp.content }])
        } catch (e2) {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: `Error: ${(e2 as Error).message || 'Failed to get response'}`
          }])
        }
      }
      setStreamText('')
    }
    setStreaming(false)
  }

  return (
    <div className="flex flex-col h-[calc(100vh-180px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-accent-blue" />
            Chat: {deckName}
          </h3>
          <p className="text-[10px] text-text-tertiary">
            {goals.metaFocus && `${goals.metaFocus} · `}
            {goals.targetPowerLevel && `Power ${goals.targetPowerLevel} · `}
            {goals.budget && `${goals.budget}`}
          </p>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-bg-hover text-text-tertiary">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !streaming && (
          <div className="text-center py-12">
            <GraduationCap className="w-10 h-10 text-text-tertiary mx-auto mb-3" />
            <p className="text-sm text-text-secondary">Ask your coach anything about this deck.</p>
            <div className="mt-4 flex flex-wrap gap-2 justify-center">
              {[
                'What should I cut?',
                'How is my mana curve?',
                'Suggest win conditions',
                'Rate my removal suite',
              ].map(q => (
                <button
                  key={q}
                  onClick={() => { setInput(q); }}
                  className="px-3 py-1.5 text-xs bg-bg-secondary border border-border-primary rounded-full text-text-secondary hover:text-text-primary hover:border-border-secondary transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] px-4 py-3 rounded-xl text-sm whitespace-pre-wrap leading-relaxed ${
              msg.role === 'user'
                ? 'bg-accent-blue/15 text-text-primary border border-accent-blue/20'
                : 'bg-bg-secondary text-text-primary border border-border-primary'
            }`}>
              {msg.content}
            </div>
          </div>
        ))}

        {/* Streaming indicator */}
        {streaming && (
          <div className="flex justify-start">
            <div className="max-w-[85%] px-4 py-3 rounded-xl text-sm whitespace-pre-wrap leading-relaxed bg-bg-secondary text-text-primary border border-border-primary">
              {streamText || (
                <span className="flex items-center gap-2 text-text-tertiary">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Thinking...
                </span>
              )}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border-primary p-3">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder="Ask the coach..."
            disabled={streaming}
            className="flex-1 px-3 py-2 bg-bg-secondary border border-border-primary rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={streaming || !input.trim()}
            className="px-3 py-2 bg-accent-blue text-white rounded-lg hover:bg-accent-blue-hover transition-colors disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// Main Coach Page
// ════════════════════════════════════════════════════════════
type Tab = 'decks' | 'chat' | 'session' | 'history' | 'search'

export function CoachPage() {
  const [status, setStatus] = useState<CoachStatus | null>(null)
  const [decks, setDecks] = useState<CoachDeck[]>([])
  const [sessions, setSessions] = useState<CoachSessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // UI state
  const [tab, setTab] = useState<Tab>('decks')
  const [selectedDeck, setSelectedDeck] = useState<CoachDeck | null>(null)
  const [selectedSession, setSelectedSession] = useState<CoachSession | null>(null)
  const [goals, setGoals] = useState<CoachGoals>({})
  const [goalsCollapsed, setGoalsCollapsed] = useState(true)
  const [generatingReport, setGeneratingReport] = useState(false)
  const [runningSession, setRunningSession] = useState<number | null>(null)
  const [downloadingEmbeddings, setDownloadingEmbeddings] = useState(false)

  const loadData = useCallback(async () => {
    try {
      const [s, d, sess] = await Promise.all([
        coachApi.getCoachStatus(),
        coachApi.getCoachDecks().catch(() => []),
        coachApi.getCoachSessions().catch(() => ({ sessions: [] })),
      ])
      setStatus(s)
      setDecks(Array.isArray(d) ? d : [])
      setSessions(Array.isArray(sess) ? sess : (sess as { sessions: CoachSessionSummary[] }).sessions || [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleDownloadEmbeddings = async () => {
    setDownloadingEmbeddings(true)
    try {
      await coachApi.downloadEmbeddings()
      const s = await coachApi.getCoachStatus()
      setStatus(s)
    } catch { /* ignore */ }
    setDownloadingEmbeddings(false)
  }

  const handleGenerateReports = async () => {
    setGeneratingReport(true)
    setError(null)
    try {
      await coachApi.generateReport()
      await loadData()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Report generation failed')
    }
    setGeneratingReport(false)
  }

  const handleRunSession = async (deck: CoachDeck) => {
    setRunningSession(deck.deck_id)
    setError(null)
    try {
      const deckSlug = deck.deck_name.toLowerCase().replace(/\s+/g, '-')
      const goalsDict = goals.targetPowerLevel || goals.metaFocus || goals.budget || (goals.focusAreas || []).length > 0
        ? goals : undefined
      const session = await coachApi.runCoachSession(deckSlug, goalsDict as Record<string, unknown>)
      setSelectedSession(session)
      setSelectedDeck(deck)
      setTab('session')
      await loadData()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Session failed')
    }
    setRunningSession(null)
  }

  const handleOpenChat = (deck: CoachDeck) => {
    setSelectedDeck(deck)
    setTab('chat')
  }

  const handleViewSession = async (sessionId: string) => {
    try {
      const s = await coachApi.getCoachSession(sessionId)
      setSelectedSession(s)
      // Find the matching deck
      const matchDeck = decks.find(d =>
        d.deck_name.toLowerCase().replace(/\s+/g, '-') === s.deckId.toLowerCase() ||
        d.deck_name.toLowerCase() === s.deckId.toLowerCase()
      )
      if (matchDeck) setSelectedDeck(matchDeck)
      setTab('session')
    } catch { /* ignore */ }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <Spinner size="lg" className="text-accent-blue" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
            <GraduationCap className="w-6 h-6 text-accent-amber" />
            Deck Coach
          </h1>
          <p className="text-sm text-text-secondary mt-0.5">
            AI-powered deck analysis, coaching, and live chat
          </p>
        </div>
      </div>

      {/* Status Bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <StatusBadge
          variant={status?.llmConnected ? 'success' : 'warning'}
          label={status?.llmConnected ? `LLM: ${status.llmModel || 'Connected'}` : 'LLM: Disconnected'}
        />
        <StatusBadge
          variant={status?.embeddingsLoaded ? 'success' : 'neutral'}
          label={status?.embeddingsLoaded ? `${(status.embeddingCards || 0).toLocaleString()} embeddings` : 'No embeddings'}
        />
        {status?.deckReportsAvailable != null && status.deckReportsAvailable > 0 && (
          <StatusBadge variant="success" label={`${status.deckReportsAvailable} reports`} />
        )}
        {!status?.embeddingsLoaded && (
          <button onClick={handleDownloadEmbeddings} disabled={downloadingEmbeddings}
            className="flex items-center gap-1.5 text-xs text-accent-blue hover:text-accent-blue-hover transition-colors disabled:opacity-50">
            {downloadingEmbeddings ? <Spinner size="sm" /> : <Download className="w-3 h-3" />}
            Download Embeddings
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-status-error/10 border border-status-error/30 rounded-lg text-sm text-status-error">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
          <button onClick={() => setError(null)} className="ml-auto"><X className="w-3 h-3" /></button>
        </div>
      )}

      {/* Tab Nav */}
      <div className="flex gap-1 bg-bg-secondary rounded-lg p-1 border border-border-primary">
        {([
          { id: 'decks', label: 'Decks', icon: ClipboardList },
          { id: 'history', label: 'Sessions', icon: History },
          { id: 'search', label: 'Cards Like', icon: Search },
        ] as { id: Tab; label: string; icon: typeof ClipboardList }[]).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === t.id
                ? 'bg-bg-primary text-text-primary shadow-sm'
                : 'text-text-tertiary hover:text-text-secondary'
            }`}
          >
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
            {t.id === 'history' && sessions.length > 0 && (
              <span className="text-[10px] bg-bg-tertiary px-1.5 rounded-full">{sessions.length}</span>
            )}
          </button>
        ))}
        {tab === 'chat' && selectedDeck && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-bg-primary text-accent-blue shadow-sm">
            <MessageSquare className="w-3.5 h-3.5" />
            Chat
          </div>
        )}
        {tab === 'session' && selectedSession && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-bg-primary text-accent-amber shadow-sm">
            <Sparkles className="w-3.5 h-3.5" />
            Results
          </div>
        )}
      </div>

      {/* Goals Panel (shown when on decks tab) */}
      {tab === 'decks' && (
        <GoalsPanel
          goals={goals}
          onChange={setGoals}
          collapsed={goalsCollapsed}
          onToggle={() => setGoalsCollapsed(!goalsCollapsed)}
        />
      )}

      {/* ── Decks Tab ─────────────────────────────────────── */}
      {tab === 'decks' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-text-primary">Your Decks</h2>
            <button
              onClick={handleGenerateReports}
              disabled={generatingReport}
              className="flex items-center gap-1.5 text-xs text-accent-amber hover:text-accent-amber transition-colors disabled:opacity-50"
            >
              {generatingReport ? <Spinner size="sm" /> : <Zap className="w-3 h-3" />}
              Generate Reports
            </button>
          </div>

          {decks.length === 0 ? (
            <EmptyState
              icon={GraduationCap}
              title="No decks available"
              description="Create decks in the Deck Builder to start coaching."
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {decks.map(deck => (
                <div key={deck.deck_id} className="bg-bg-secondary rounded-xl border border-border-primary p-4 space-y-3">
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">{deck.deck_name}</h3>
                    <p className="text-xs text-text-secondary">{deck.commander}</p>
                  </div>
                  <div className="flex items-center gap-3 text-[10px] text-text-tertiary">
                    <span>{deck.card_count} cards</span>
                    {deck.has_report && (
                      <span className="flex items-center gap-1 text-status-success">
                        <Check className="w-2.5 h-2.5" /> Report
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleRunSession(deck)}
                      disabled={runningSession === deck.deck_id || !status?.llmConnected}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-accent-amber/15 text-accent-amber text-xs font-medium rounded-lg hover:bg-accent-amber/25 border border-accent-amber/30 transition-colors disabled:opacity-50"
                    >
                      {runningSession === deck.deck_id ? <Spinner size="sm" /> : <Sparkles className="w-3 h-3" />}
                      Analyze
                    </button>
                    <button
                      onClick={() => handleOpenChat(deck)}
                      disabled={!status?.llmConnected}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-accent-blue/15 text-accent-blue text-xs font-medium rounded-lg hover:bg-accent-blue/25 border border-accent-blue/30 transition-colors disabled:opacity-50"
                    >
                      <MessageSquare className="w-3 h-3" />
                      Chat
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Chat Tab ──────────────────────────────────────── */}
      {tab === 'chat' && selectedDeck && (
        <LiveChat
          deckId={selectedDeck.deck_name.toLowerCase().replace(/\s+/g, '-')}
          deckName={selectedDeck.deck_name}
          goals={goals}
          onClose={() => setTab('decks')}
        />
      )}

      {/* ── Session Results Tab ───────────────────────────── */}
      {tab === 'session' && selectedSession && selectedDeck && (
        <SessionView
          session={selectedSession}
          deckId={selectedDeck.deck_id}
          onClose={() => setTab('decks')}
          onApplied={() => loadData()}
        />
      )}

      {/* ── History Tab ───────────────────────────────────── */}
      {tab === 'history' && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-text-primary">Coaching Sessions</h2>
          {sessions.length === 0 ? (
            <EmptyState
              icon={History}
              title="No sessions yet"
              description="Run an analysis on a deck to create your first coaching session."
            />
          ) : (
            <div className="space-y-2">
              {sessions.map(s => (
                <button
                  key={s.sessionId}
                  onClick={() => handleViewSession(s.sessionId)}
                  className="w-full flex items-center gap-4 px-4 py-3 bg-bg-secondary rounded-lg border border-border-primary hover:border-border-secondary text-left transition-colors"
                >
                  <Sparkles className="w-4 h-4 text-accent-amber flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-text-primary">{s.deckId}</p>
                      <span className="text-[10px] text-text-tertiary">
                        {s.cutsCount > 0 && `${s.cutsCount} cuts`}
                        {s.cutsCount > 0 && s.addsCount > 0 && ' · '}
                        {s.addsCount > 0 && `${s.addsCount} adds`}
                      </span>
                    </div>
                    <p className="text-xs text-text-tertiary mt-0.5 truncate">{s.summary || 'No summary'}</p>
                    <p className="text-[10px] text-text-tertiary mt-0.5">{new Date(s.timestamp).toLocaleString()}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-text-tertiary flex-shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Cards Like Tab ────────────────────────────────── */}
      {tab === 'search' && (
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-text-primary mb-1">Cards Like This</h2>
            <p className="text-xs text-text-secondary">
              Find similar cards using AI embeddings. Search by card name to discover alternatives.
            </p>
          </div>
          <CardsLikePanel />
        </div>
      )}
    </div>
  )
}
