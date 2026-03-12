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
  llm_connected: boolean
  active_model: string | null
  embeddings_loaded: boolean
  embedding_cards: number
}

export interface CoachDeck {
  deck_id: number
  deck_name: string
  commander: string
  report_count: number
  last_report_date: string | null
}

export interface CoachSession {
  session_id: string
  deck_name: string
  created_at: string
  messages: CoachMessage[]
}

export interface CoachMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

// ── ML Training ──────────────────────────────────────────────

export interface MLStatus {
  enabled: boolean
  model_loaded: boolean
  model_path: string | null
  decisions_count: number
  decision_files: string[]
}

export interface MLDataStatus {
  dataset_exists: boolean
  samples: number
  features: number
  last_built: string | null
}

export interface MLTrainStatus {
  running: boolean
  epoch: number
  total_epochs: number
  loss: number | null
  accuracy: number | null
  best_accuracy: number | null
}

export interface PPOTrainStatus {
  running: boolean
  iteration: number
  total_iterations: number
  avg_reward: number | null
  win_rate: number | null
}

export interface TournamentStatus {
  running: boolean
  games_completed: number
  total_games: number
}

export interface TournamentResults {
  players: TournamentPlayer[]
  total_games: number
}

export interface TournamentPlayer {
  name: string
  wins: number
  games: number
  win_rate: number
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
