export type Phase =
  | 'untap' | 'upkeep' | 'draw' | 'main1'
  | 'begin_combat' | 'declare_attackers' | 'declare_blockers' | 'combat_damage'
  | 'main2' | 'end_step' | 'cleanup';

export interface Card {
  name: string;
  type: string;
  tapped: boolean;
  is_commander: boolean;
  oracle: string;
  cmc: number;
}

export interface Player {
  seat: number;
  name: string;
  life: number;
  eliminated: boolean;
  hand: Card[];
  battlefield: Card[];
  graveyard: Card[];
  exile: Card[];
  command_zone: Card[];
  hand_count: number;
}

export interface GameState {
  game_id: string;
  turn: number;
  current_phase: Phase;
  active_seat: number;
  players: Player[];
  stack: Card[];
  game_over: boolean;
  winner: Player | null;
}

export type WsIncoming =
  | { type: 'state'; payload: GameState }
  | { type: 'event'; text: string; seat?: number }
  | { type: 'phase'; phase: Phase; active_seat: number }
  | { type: 'thinking'; seat: number; active: boolean }
  | { type: 'elimination'; seat: number }
  | { type: 'game_over'; winner: number; reason: string }
  | { type: 'hand'; cards: Card[] }
  | { type: 'pong' }
  | { type: 'error'; message: string };

export interface NarrationLine {
  text: string;
  seat?: number;
  isSystem: boolean;
  timestamp: number;
}
