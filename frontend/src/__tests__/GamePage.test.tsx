import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import GamePage from '../pages/GamePage';
import type { GameState, Card } from '../types/game';

const mockGameState: GameState = {
  game_id: 'test-game',
  turn: 1,
  current_phase: 'main1',
  active_seat: 0,
  players: [
    {
      seat: 0, name: 'Alice', life: 40, eliminated: false,
      hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 7,
    },
    {
      seat: 1, name: 'Bob', life: 38, eliminated: false,
      hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 6,
    },
    {
      seat: 2, name: 'Charlie', life: 40, eliminated: false,
      hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 7,
    },
    {
      seat: 3, name: 'Diana', life: 35, eliminated: false,
      hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 5,
    },
  ],
  stack: [],
  game_over: false,
  winner: null,
};

const mockHand: Card[] = [];
const mockSendMove = vi.fn();
const mockSendConcede = vi.fn();

vi.mock('../hooks/useGameSocket', () => ({
  useGameSocket: () => ({
    gameState: mockGameState,
    narration: [],
    thinking: new Set<number>(),
    hand: mockHand,
    gameOver: null,
    status: 'Connected',
    sendMove: mockSendMove,
    sendConcede: mockSendConcede,
  }),
}));

describe('GamePage integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders all 4 PlayerZone components', () => {
    render(
      <MemoryRouter initialEntries={['/game/test-game']}>
        <Routes>
          <Route path="/game/:gameId" element={<GamePage />} />
        </Routes>
      </MemoryRouter>,
    );

    // P0: Alice appears in both PhaseBar and PlayerZone, so use getAllByText
    expect(screen.getAllByText(/P0: Alice/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/P1: Bob/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/P2: Charlie/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/P3: Diana/).length).toBeGreaterThanOrEqual(1);
  });

  it('renders PhaseBar with current phase', () => {
    render(
      <MemoryRouter initialEntries={['/game/test-game']}>
        <Routes>
          <Route path="/game/:gameId" element={<GamePage />} />
        </Routes>
      </MemoryRouter>,
    );

    // main1 should be highlighted
    const main1Buttons = screen.getAllByText('main1');
    expect(main1Buttons.length).toBeGreaterThan(0);
  });
});
