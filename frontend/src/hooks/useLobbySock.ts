import { useReducer, useRef, useEffect, useCallback } from 'react';

export interface Seat {
  seat: number;
  name: string;
  ready: boolean;
  isAi: boolean;
}

export interface RoomState {
  roomId: string;
  roomName: string;
  host: string;
  seats: (Seat | null)[];
}

export interface ChatMessage {
  role: 'PLAYER' | 'AI' | 'SYSTEM';
  name: string;
  text: string;
  timestamp: number;
}

type LobbyAction =
  | { type: 'SET_ROOM'; payload: RoomState }
  | { type: 'ADD_CHAT'; message: ChatMessage }
  | { type: 'SET_CHAT_HISTORY'; messages: ChatMessage[] }
  | { type: 'LAUNCH'; gameId: string };

interface LobbyState {
  roomState: RoomState | null;
  chat: ChatMessage[];
  launchedGameId: string | null;
}

const initialState: LobbyState = {
  roomState: null,
  chat: [],
  launchedGameId: null,
};

function lobbyReducer(state: LobbyState, action: LobbyAction): LobbyState {
  switch (action.type) {
    case 'SET_ROOM':
      return { ...state, roomState: action.payload };
    case 'ADD_CHAT':
      return { ...state, chat: [...state.chat, action.message].slice(-50) };
    case 'SET_CHAT_HISTORY':
      return { ...state, chat: action.messages.slice(-50) };
    case 'LAUNCH':
      return { ...state, launchedGameId: action.gameId };
    default:
      return state;
  }
}

export function useLobbySock(roomId: string, playerName: string) {
  const [state, dispatch] = useReducer(lobbyReducer, initialState);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatInterval = useRef<ReturnType<typeof setInterval> | null>(null);
  const intentionalClose = useRef(false);

  const connect = useCallback(() => {
    const url = `ws://${window.location.host}/ws/lobby/${roomId}?name=${encodeURIComponent(playerName)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case 'lobby_state':
          dispatch({ type: 'SET_ROOM', payload: msg.payload });
          break;
        case 'chat':
          dispatch({
            type: 'ADD_CHAT',
            message: {
              role: msg.role ?? 'PLAYER',
              name: msg.name ?? '',
              text: msg.text,
              timestamp: Date.now(),
            },
          });
          break;
        case 'chat_history':
          dispatch({
            type: 'SET_CHAT_HISTORY',
            messages: (msg.messages ?? []).map((m: { role?: string; name?: string; text: string }) => ({
              role: m.role ?? 'SYSTEM',
              name: m.name ?? '',
              text: m.text,
              timestamp: Date.now(),
            })),
          });
          break;
        case 'launch':
          dispatch({ type: 'LAUNCH', gameId: msg.game_id });
          break;
        case 'pong':
          break;
      }
    };

    ws.onclose = () => {
      if (!intentionalClose.current) {
        reconnectTimeout.current = setTimeout(() => connect(), 3000);
      }
    };
  }, [roomId, playerName]);

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

  const sendReady = useCallback((seat: number) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ready', seat }));
    }
  }, []);

  const sendChat = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'chat', text }));
    }
  }, []);

  const sendLaunch = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'launch' }));
    }
  }, []);

  return {
    roomState: state.roomState,
    chat: state.chat,
    launchedGameId: state.launchedGameId,
    sendReady,
    sendChat,
    sendLaunch,
  };
}
