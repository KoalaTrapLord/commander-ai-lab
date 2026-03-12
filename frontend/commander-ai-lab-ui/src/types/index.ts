// ═══════════════════════════════════════════════════════════
// Commander AI Lab — TypeScript Type Definitions
// Derived from the FastAPI backend's Pydantic models + SQLite schema
// ═══════════════════════════════════════════════════════════

// ── Cards & Collection ──────────────────────────────────────

export interface CollectionCard {
  id: number
  name: string
  scryfall_id: string
  set_code: string
  set_name: string
  collector_number: string
  rarity: string
  type_line: string
  mana_cost: string
  cmc: number
  oracle_text: string
  color_identity: string[]
  quantity: number
  foil_quantity: number
  condition: string
  tcg_price: number | null
  foil_price: number | null
  image_url: string
  edhrec_rank: number | null
  keywords: string
  added_date: string
  updated_date: string
}

export interface CollectionFilters {
  q?: string
  type_line?: string
  color?: string
  rarity?: string
  set_code?: string
  cmc_min?: number
  cmc_max?: number
  price_min?: number
  price_max?: number
  owned_only?: boolean
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export interface CollectionStats {
  total_cards: number
  total_unique: number
  total_value: number
  sets_count: number
}

export interface SetInfo {
  code: string
  name: string
  card_count: number
}

// ── Scan ─────────────────────────────────────────────────────

export interface ScanResult {
  matches: ScanMatch[]
  image_url?: string
}

export interface ScanMatch {
  name: string
  set_code: string
  set_name: string
  collector_number: string
  scryfall_id: string
  confidence: number
  image_url: string
  type_line: string
  oracle_text: string
  mana_cost: string
  tcg_price: number | null
}

// ── Decks ────────────────────────────────────────────────────

export interface Deck {
  id: number
  name: string
  commander: string
  commander_scryfall_id?: string
  commander_image_url?: string
  color_identity: string[]
  format: string
  card_count: number
  total_price: number
  created_date: string
  updated_date: string
}

export interface DeckCard {
  id: number
  deck_id: number
  name: string
  scryfall_id: string
  quantity: number
  is_commander: boolean
  category: string
  type_line: string
  mana_cost: string
  cmc: number
  oracle_text: string
  tcg_price: number | null
  image_url: string
  owned_qty: number
  set_code: string
}

export interface DeckAnalysis {
  card_count: number
  land_count: number
  creature_count: number
  noncreature_count: number
  avg_cmc: number
  mana_curve: Record<number, number>
  color_distribution: Record<string, number>
  type_distribution: Record<string, number>
  total_price: number
  owned_count: number
  missing_count: number
}

export interface DeckRecommendation {
  name: string
  scryfall_id: string
  type_line: string
  mana_cost: string
  oracle_text: string
  image_url: string
  tcg_price: number | null
  reason: string
  score: number
  owned: boolean
}

// ── EDHREC Recommendations ──────────────────────────────────

export interface EdhRecCard {
  name: string
  type_line: string
  role: string
  roles: string[]
  inclusion_pct: number | null
  synergy_score: number | null
  owned: boolean
  owned_qty: number
  scryfall_id: string
  image_url: string | null
}

export interface EdhRecsResponse {
  commander: string
  source: string
  total: number
  recommendations: EdhRecCard[]
}

// ── Collection Recommendations ──────────────────────────────

export interface CollectionRecCard {
  id: number
  scryfall_id: string
  name: string
  type_line: string
  card_type: string
  cmc: number
  color_identity: string[]
  owned_qty: number
  roles: string[]
  score: number
  image_url: string | null
}

export interface CollectionRecsResponse {
  shortfall_types: string[]
  role_filter: string[]
  grouped: Record<string, CollectionRecCard[]>
  total: number
}

// ── V3 Deck Generator ────────────────────────────────────────

export interface DeckGenV3Request {
  commander_name: string
  strategy?: string
  target_bracket: number
  budget_usd?: number
  budget_mode?: 'total' | 'per_card'
  omit_cards?: string[]
  use_collection?: boolean
  run_substitution?: boolean
  model?: string
  deck_name?: string
}

export interface DeckGenV3Status {
  initialized: boolean
  pplx_configured: boolean
  model: string | null
  embeddings_loaded: boolean
  embedding_cards: number
  error: string | null
}

export interface DeckGenV3Card {
  name: string
  quantity: number
  category: string
  type_line: string
  mana_cost: string
  cmc: number
  role: string
  reason: string
  tcg_price: number | null
  image_url: string
  owned: boolean
  owned_qty: number
  scryfall_id: string
  is_substitute: boolean
  original_name: string | null
  substitution_reason: string | null
  similarity_score: number | null
}

export interface DeckGenV3Result {
  commander: {
    name: string
    image_url: string
    type_line: string
    color_identity: string[]
    mana_cost: string
    oracle_text: string
  }
  cards: DeckGenV3Card[]
  stats: DeckAnalysis
  strategy: string
  bracket: number
  model: string
  substitution?: {
    owned: number
    substituted: number
    missing: number
  }
}

// ── Simulation ───────────────────────────────────────────────

export interface SimConfig {
  deck_names: string[]
  num_games: number
  threads: number
  use_deepseek?: boolean
}

export interface SimStatus {
  running: boolean
  sim_id: string
  progress?: number
  games_completed?: number
  total_games?: number
}

export interface SimResult {
  sim_id: string
  decks: SimDeckResult[]
  total_games: number
  duration_ms: number
  timestamp: string
}

export interface SimDeckResult {
  name: string
  wins: number
  losses: number
  win_rate: number
  avg_turn: number
}

// ── Batch Sim (Lab) ──────────────────────────────────────────

export interface LabDeck {
  name: string
  source: string
  path: string
  card_count: number
}

export interface LabStartRequest {
  decks: string[]
  games: number
  threads?: number
  use_deepseek?: boolean
  deepseek_deck?: string
}

export interface LabStatus {
  running: boolean
  run_id: string
  games_completed: number
  total_games: number
  current_decks: string[]
  error: string | null
}

export interface LabResult {
  run_id: string
  decks: LabDeckResult[]
  total_games: number
  timestamp: string
}

export interface LabDeckResult {
  name: string
  wins: number
  games: number
  win_rate: number
  avg_turns: number
  avg_life_remaining: number
}

export interface LabHistoryEntry {
  run_id: string
  timestamp: string
  decks: string[]
  total_games: number
}

export interface PreconDeck {
  name: string
  filename: string
  release_date?: string
  set_name?: string
  installed: boolean
}

// ── Coach ────────────────────────────────────────────────────

export interface CoachStatus {
  llmConnected: boolean
  llmModel: string | null
  llmModels: string[]
  embeddingsLoaded: boolean
  embeddingCards: number
  deckReportsAvailable: number
  error: string | null
}

export interface CoachDeck {
  deck_id: number
  deck_name: string
  commander: string
  card_count: number
  has_report: boolean
  report_count: number
  last_report_date: string | null
}

export interface CoachGoals {
  targetPowerLevel?: number | null
  metaFocus?: string | null
  budget?: string | null
  focusAreas?: string[]
}

export interface CoachMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface CoachChatResponse {
  content: string
  model: string
  prompt_tokens: number
  completion_tokens: number
}

export interface CoachSession {
  sessionId: string
  deckId: string
  timestamp: string
  summary: string
  suggestedCuts: CoachSuggestedCut[]
  suggestedAdds: CoachSuggestedAdd[]
  heuristicHints: string[]
  manaBaseAdvice: string | null
  rawTextExplanation: string
  modelUsed: string
  promptTokens: number
  completionTokens: number
  goals: CoachGoals | null
}

export interface CoachSuggestedCut {
  cardName: string
  reason: string
  replacementOptions: string[]
  currentImpactScore: number
}

export interface CoachSuggestedAdd {
  cardName: string
  role: string
  reason: string
  synergyWith: string[]
  estimatedManaValue: number | null
}

export interface CoachSessionSummary {
  sessionId: string
  deckId: string
  timestamp: string
  summary: string
  cutsCount: number
  addsCount: number
}

export interface CoachApplyResult {
  cuts: { name: string; status: string }[]
  adds: { name: string; scryfall_id?: string; status: string }[]
  errors: { name: string; error: string }[]
  total_cuts: number
  total_adds: number
}

export interface CoachCardLikeResult {
  name: string
  similarity: number
  types: string
  mana_value: number
  mana_cost: string
  text: string
  owned_qty: number
  image_url: string | null
  tcg_price: number | null
}

// ── ML Training ──────────────────────────────────────────────

/** GET /api/ml/status */
export interface MLStatus {
  ml_logging_enabled: boolean
  training_files: { file: string; decisions: number; size_kb: number }[]
  total_decisions: number
  total_files: number
}

/** GET /api/ml/data/status */
export interface MLDataStatus {
  decisionFiles: { name: string; size: number; decisions: number }[]
  totalDecisions: number
  datasets: Record<string, { samples: number; features: number; size: number }>
  checkpoints: { name: string; size: number; modified: string }[]
  evalResults: Record<string, unknown> | null
  policyLoaded: boolean
}

/** GET /api/ml/train/status */
export interface MLTrainStatus {
  running: boolean
  progress: number
  total_epochs: number
  current_epoch: number
  phase: 'idle' | 'starting' | 'building' | 'training' | 'evaluating' | 'done' | 'error'
  message: string
  metrics: Record<string, unknown> | null
  result: {
    training: Record<string, unknown>
    evaluation: Record<string, unknown> | null
    checkpoint: string
    device: string
  } | null
  error: string | null
  started_at: string | null
}

/** GET /api/ml/train/ppo/status */
export interface PPOTrainStatus {
  running: boolean
  iteration: number
  total_iterations: number
  phase: 'idle' | 'starting' | 'training' | 'done' | 'error'
  message: string
  metrics: {
    avg_reward?: number
    win_rate?: number
    policy_loss?: number
    value_loss?: number
    entropy?: number
    [key: string]: unknown
  } | null
  result: Record<string, unknown> | null
  error: string | null
}

/** GET /api/ml/tournament/status */
export interface TournamentStatus {
  running: boolean
  phase: 'idle' | 'starting' | 'running' | 'done' | 'error'
  message: string
  result: TournamentResults | null
  error: string | null
}

export interface TournamentResults {
  players: TournamentPlayer[]
  total_matches: number
  matchups?: Record<string, unknown>
}

export interface TournamentPlayer {
  name: string
  wins: number
  games: number
  win_rate: number
}

/** GET /api/ml/model */
export interface MLModelInfo {
  loaded: boolean
  device?: string
  input_dim?: number
  num_actions?: number
  checkpoint_path?: string
  error?: string
  torch_available?: boolean
}

// ── DeepSeek ─────────────────────────────────────────────────

export interface DeepSeekStatus {
  connected: boolean
  model: string | null
  base_url: string
}

// ── Commander Search ─────────────────────────────────────────

export interface CommanderSearchResult {
  name: string
  type_line: string
  color_identity: string[]
  mana_cost: string
  image_url: string
  oracle_text: string
  scryfall_id: string
  in_collection: boolean
}

// ── Perplexity ───────────────────────────────────────────────

export interface PplxStatus {
  configured: boolean
  key_prefix: string
}
