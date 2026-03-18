import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import PlayerZone from '../components/PlayerZone';
import type { Player } from '../types/game';

function makePlayer(overrides: Partial<Player> = {}): Player {
  return {
    seat: 0, name: 'Alice', life: 40, eliminated: false,
    hand: [], battlefield: [], graveyard: [], exile: [], command_zone: [], hand_count: 7,
    ...overrides,
  };
}

describe('PlayerZone life colors', () => {
  it('uses life-high color for life >= 30', () => {
    render(<PlayerZone player={makePlayer({ life: 35 })} isActive={false} isThinking={false} seatColour="#4696ff" />);
    const life = screen.getByText('35');
    expect(life).toHaveClass('text-life-high');
  });

  it('uses life-med color for life >= 15 and < 30', () => {
    render(<PlayerZone player={makePlayer({ life: 20 })} isActive={false} isThinking={false} seatColour="#4696ff" />);
    const life = screen.getByText('20');
    expect(life).toHaveClass('text-life-med');
  });

  it('uses life-low color for life < 15', () => {
    render(<PlayerZone player={makePlayer({ life: 10 })} isActive={false} isThinking={false} seatColour="#4696ff" />);
    const life = screen.getByText('10');
    expect(life).toHaveClass('text-life-low');
  });
});
