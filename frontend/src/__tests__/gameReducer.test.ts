import { describe, it, expect } from 'vitest';
import { gameReducer, initialState } from '../store/gameReducer';
import type { GameState, Card, NarrationLine } from '../types/game';

const mockGameState: GameState = {
  game_id: 'g1',
  turn: 1,
  current_phase: 'main1',
  active_seat: 0,
  players: [],
  stack: [],
  game_over: false,
  winner: null,
};

const mockCard: Card = {
  name: 'Sol Ring',
  type: 'Artifact',
  tapped: false,
  is_commander: false,
  oracle: '',
  cmc: 1,
};

const mockLine: NarrationLine = {
  text: 'Test narration',
  isSystem: false,
  timestamp: Date.now(),
};

describe('gameReducer', () => {
  it('SET_STATE sets the game state', () => {
    const result = gameReducer(initialState, { type: 'SET_STATE', payload: mockGameState });
    expect(result.gameState).toEqual(mockGameState);
  });

  it('SET_HAND sets the hand cards', () => {
    const cards = [mockCard];
    const result = gameReducer(initialState, { type: 'SET_HAND', cards });
    expect(result.hand).toEqual(cards);
  });

  it('ADD_NARRATION appends a line', () => {
    const result = gameReducer(initialState, { type: 'ADD_NARRATION', line: mockLine });
    expect(result.narration).toHaveLength(1);
    expect(result.narration[0].text).toBe('Test narration');
  });

  it('ADD_NARRATION caps at 120 lines', () => {
    let state = initialState;
    for (let i = 0; i < 130; i++) {
      state = gameReducer(state, {
        type: 'ADD_NARRATION',
        line: { text: `line ${i}`, isSystem: false, timestamp: Date.now() },
      });
    }
    expect(state.narration).toHaveLength(120);
    expect(state.narration[0].text).toBe('line 10');
  });

  it('SET_THINKING adds and removes seats', () => {
    let state = gameReducer(initialState, { type: 'SET_THINKING', seat: 2, active: true });
    expect(state.thinkingSeats.has(2)).toBe(true);

    state = gameReducer(state, { type: 'SET_THINKING', seat: 2, active: false });
    expect(state.thinkingSeats.has(2)).toBe(false);
  });

  it('GAME_OVER sets winner and reason', () => {
    const result = gameReducer(initialState, { type: 'GAME_OVER', winner: 1, reason: 'elimination' });
    expect(result.gameOver).toEqual({ winner: 1, reason: 'elimination' });
  });

  it('SET_STATUS sets status text', () => {
    const result = gameReducer(initialState, { type: 'SET_STATUS', status: 'Connected' });
    expect(result.status).toBe('Connected');
  });
});
