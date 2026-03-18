import { useReducer, useRef, useEffect, useCallback } from 'react';
import { gameReducer, initialState } from '../store/gameReducer';
import type { WsIncoming, NarrationLine } from '../types/game';

export function useGameSocket(gameId: string) {
  const [state, dispatch] = useReducer(gameReducer, initialState);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatInterval = useRef<ReturnType<typeof setInterval> | null>(null);
  const intentionalClose = useRef(false);

  const connect = useCallback(() => {
    const url = `ws://${window.location.host}/ws/game/${gameId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      dispatch({ type: 'SET_STATUS', status: 'Connected' });
    };

    ws.onmessage = (event) => {
      const msg: WsIncoming = JSON.parse(event.data);

      switch (msg.type) {
        case 'state':
          dispatch({ type: 'SET_STATE', payload: msg.payload });
          break;

        case 'hand':
          dispatch({ type: 'SET_HAND', cards: msg.cards });
          break;

        case 'event': {
          const line: NarrationLine = {
            text: msg.text,
            seat: msg.seat,
            isSystem: false,
            timestamp: Date.now(),
          };
          dispatch({ type: 'ADD_NARRATION', line });
          break;
        }

        case 'phase': {
          const line: NarrationLine = {
            text: `Phase: ${msg.phase} (P${msg.active_seat})`,
            isSystem: true,
            timestamp: Date.now(),
          };
          dispatch({ type: 'ADD_NARRATION', line });
          break;
        }

        case 'thinking':
          dispatch({ type: 'SET_THINKING', seat: msg.seat, active: msg.active });
          break;

        case 'game_over':
          dispatch({ type: 'GAME_OVER', winner: msg.winner, reason: msg.reason });
          break;

        case 'pong':
          break;

        case 'error':
          dispatch({ type: 'SET_STATUS', status: `Error: ${msg.message}` });
          break;
      }
    };

    ws.onclose = () => {
      if (!intentionalClose.current) {
        dispatch({ type: 'SET_STATUS', status: 'Disconnected — reconnecting…' });
        reconnectTimeout.current = setTimeout(() => {
          connect();
        }, 3000);
      }
    };

    ws.onerror = () => {
      dispatch({ type: 'SET_STATUS', status: 'Connection error' });
    };
  }, [gameId]);

  // Connect on mount
  useEffect(() => {
    intentionalClose.current = false;
    connect();

    return () => {
      intentionalClose.current = true;
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Heartbeat ping every 15s
  useEffect(() => {
    heartbeatInterval.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 15000);

    return () => {
      if (heartbeatInterval.current) clearInterval(heartbeatInterval.current);
    };
  }, []);

  const sendMove = useCallback((move: string, data?: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'move', move, ...data }));
    }
  }, []);

  const sendConcede = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'concede' }));
    }
  }, []);

  return {
    gameState: state.gameState,
    narration: state.narration,
    thinking: state.thinkingSeats,
    hand: state.hand,
    gameOver: state.gameOver,
    status: state.status,
    sendMove,
    sendConcede,
  };
}
