import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import PhaseBar from '../components/PhaseBar';
import type { Player } from '../types/game';

const players: Player[] = [
  {
    seat: 0, name: 'Alice', life: 40, eliminated: false,
    hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 7,
  },
  {
    seat: 1, name: 'Bob', life: 40, eliminated: false,
    hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 7,
  },
];

describe('PhaseBar', () => {
  it('highlights the active phase tab', () => {
    render(<PhaseBar phase="main1" activeSeat={0} players={players} />);

    const main1 = screen.getByText('main1');
    expect(main1).toHaveClass('bg-accent-blue');
  });

  it('does not highlight inactive phase tabs', () => {
    render(<PhaseBar phase="main1" activeSeat={0} players={players} />);

    const untap = screen.getByText('untap');
    expect(untap).not.toHaveClass('bg-accent-blue');
    expect(untap).toHaveClass('bg-[#252a42]');
  });

  it('shows active player name', () => {
    render(<PhaseBar phase="main1" activeSeat={0} players={players} />);

    expect(screen.getByText(/P0: Alice/)).toBeInTheDocument();
  });
});
