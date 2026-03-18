import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useGameSocket } from '../hooks/useGameSocket';

// Mock WebSocket
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: MockWebSocket[] = [];
  url: string;
  readyState = 1; // OPEN
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // Simulate connection open
    setTimeout(() => this.onopen?.(new Event('open')), 0);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
  }

  simulateMessage(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }
}

describe('useGameSocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('dispatches state on WS message', () => {
    const { result } = renderHook(() => useGameSocket('game-1'));

    const ws = MockWebSocket.instances[0];
    const mockState = {
      game_id: 'game-1', turn: 1, current_phase: 'main1', active_seat: 0,
      players: [], stack: [], game_over: false, winner: null,
    };

    act(() => {
      ws.simulateMessage({ type: 'state', payload: mockState });
    });

    expect(result.current.gameState).toEqual(mockState);
  });

  it('dispatches hand cards on WS message', () => {
    const { result } = renderHook(() => useGameSocket('game-1'));
    const ws = MockWebSocket.instances[0];

    const cards = [{ name: 'Sol Ring', type: 'Artifact', tapped: false, is_commander: false, oracle: '', cmc: 1 }];

    act(() => {
      ws.simulateMessage({ type: 'hand', cards });
    });

    expect(result.current.hand).toEqual(cards);
  });

  it('sends heartbeat ping every 15s', () => {
    renderHook(() => useGameSocket('game-1'));
    const ws = MockWebSocket.instances[0];

    act(() => {
      vi.advanceTimersByTime(15000);
    });

    expect(ws.sent).toContain(JSON.stringify({ type: 'ping' }));
  });
});
