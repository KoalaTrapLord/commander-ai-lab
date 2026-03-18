import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import MoveBar from '../components/MoveBar';

describe('MoveBar', () => {
  it('calls onPass when pass button is clicked', async () => {
    const onPass = vi.fn();
    render(
      <MoveBar
        hand={[]}
        humanSeat={0}
        onPass={onPass}
        onConcede={vi.fn()}
        onPlayCard={vi.fn()}
        status=""
      />,
    );

    await userEvent.click(screen.getByText('Pass Priority'));
    expect(onPass).toHaveBeenCalledOnce();
  });

  it('shows confirm dialog on concede', async () => {
    const onConcede = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(
      <MoveBar
        hand={[]}
        humanSeat={0}
        onPass={vi.fn()}
        onConcede={onConcede}
        onPlayCard={vi.fn()}
        status=""
      />,
    );

    await userEvent.click(screen.getByText('Concede'));
    expect(confirmSpy).toHaveBeenCalledWith('Are you sure you want to concede?');
    expect(onConcede).toHaveBeenCalledOnce();

    confirmSpy.mockRestore();
  });

  it('does not concede if confirm is cancelled', async () => {
    const onConcede = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(
      <MoveBar
        hand={[]}
        humanSeat={0}
        onPass={vi.fn()}
        onConcede={onConcede}
        onPlayCard={vi.fn()}
        status=""
      />,
    );

    await userEvent.click(screen.getByText('Concede'));
    expect(onConcede).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });
});
