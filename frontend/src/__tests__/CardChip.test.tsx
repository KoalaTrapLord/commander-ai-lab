import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import CardChip from '../components/CardChip';
import type { Card } from '../types/game';

function makeCard(overrides: Partial<Card> = {}): Card {
  return {
    name: 'Sol Ring',
    type: 'Artifact',
    tapped: false,
    is_commander: false,
    oracle: 'Tap: Add CC.',
    cmc: 1,
    ...overrides,
  };
}

describe('CardChip', () => {
  it('applies opacity class when tapped', () => {
    render(<CardChip card={makeCard({ tapped: true })} />);
    const chip = screen.getByText(/Sol Ring/);
    expect(chip.closest('span')).toHaveClass('opacity-55');
  });

  it('shows star for commander cards', () => {
    render(<CardChip card={makeCard({ is_commander: true })} />);
    expect(screen.getByText('★')).toBeInTheDocument();
  });

  it('has hover border class', () => {
    render(<CardChip card={makeCard()} />);
    const chip = screen.getByText(/Sol Ring/).closest('span');
    expect(chip).toHaveClass('hover:border-[#ffdc32]');
  });
});
