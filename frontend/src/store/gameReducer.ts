import type { GameState, Card, NarrationLine } from '../types/game';

export type GameAction =
  | { type: 'SET_STATE'; payload: GameState }
  | { type: 'SET_HAND'; cards: Card[] }
  | { type: 'ADD_NARRATION'; line: NarrationLine }
  | { type: 'SET_THINKING'; seat: number; active: boolean }
  | { type: 'GAME_OVER'; winner: number; reason: string }
  | { type: 'SET_STATUS'; status: string };

export interface ReducerState {
  gameState: GameState | null;
  hand: Card[];
  narration: NarrationLine[];
  thinkingSeats: Set<number>;
  gameOver: { winner: number; reason: string } | null;
  status: string;
}

export const initialState: ReducerState = {
  gameState: null,
  hand: [],
  narration: [],
  thinkingSeats: new Set(),
  gameOver: null,
  status: '',
};

export function gameReducer(state: ReducerState, action: GameAction): ReducerState {
  switch (action.type) {
    case 'SET_STATE':
      return { ...state, gameState: action.payload };

    case 'SET_HAND':
      return { ...state, hand: action.cards };

    case 'ADD_NARRATION': {
      const narration = [...state.narration, action.line];
      return { ...state, narration: narration.slice(-120) };
    }

    case 'SET_THINKING': {
      const thinkingSeats = new Set(state.thinkingSeats);
      if (action.active) {
        thinkingSeats.add(action.seat);
      } else {
        thinkingSeats.delete(action.seat);
      }
      return { ...state, thinkingSeats };
    }

    case 'GAME_OVER':
      return { ...state, gameOver: { winner: action.winner, reason: action.reason } };

    case 'SET_STATUS':
      return { ...state, status: action.status };

    default:
      return state;
  }
}
