import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import NarrationPanel from '../components/NarrationPanel';
import type { NarrationLine } from '../types/game';

describe('NarrationPanel', () => {
  it('renders only 120 lines when given more', () => {
    const lines: NarrationLine[] = Array.from({ length: 150 }, (_, i) => ({
      text: `Line ${i}`,
      isSystem: false,
      timestamp: Date.now(),
    }));

    render(<NarrationPanel lines={lines} thinkingSeats={new Set()} />);

    // Should not render the first 30 lines (0-29)
    expect(screen.queryByText('Line 0')).not.toBeInTheDocument();
    expect(screen.queryByText('Line 29')).not.toBeInTheDocument();

    // Should render lines 30-149
    expect(screen.getByText('Line 30')).toBeInTheDocument();
    expect(screen.getByText('Line 149')).toBeInTheDocument();
  });

  it('has a scroll container ref', () => {
    const lines: NarrationLine[] = [
      { text: 'Hello world', isSystem: false, timestamp: Date.now() },
    ];

    const { container } = render(
      <NarrationPanel lines={lines} thinkingSeats={new Set()} />,
    );

    // The container div has overflow-y-auto
    const panel = container.firstChild as HTMLElement;
    expect(panel).toHaveClass('overflow-y-auto');
  });
});
