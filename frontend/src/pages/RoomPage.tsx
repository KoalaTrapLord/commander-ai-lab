import { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { useLobbySock } from '../hooks/useLobbySock';
import type { ChatMessage } from '../hooks/useLobbySock';

const ROLE_COLORS: Record<string, string> = {
  PLAYER: 'text-accent-blue',
  AI: 'text-accent-purple',
  SYSTEM: 'text-text-muted',
};

function ChatBadge({ role }: { role: string }) {
  return (
    <span className={`text-[10px] font-bold mr-1 ${ROLE_COLORS[role] ?? 'text-text-muted'}`}>
      [{role}]
    </span>
  );
}

export default function RoomPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const isSpectator = searchParams.get('spectate') === '1';
  const nameFromUrl = searchParams.get('name') ?? '';
  const [playerName, setPlayerName] = useState(nameFromUrl);
  const [nameConfirmed, setNameConfirmed] = useState(!!nameFromUrl);
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);

  const { roomState, chat, launchedGameId, sendReady, sendChat, sendLaunch } =
    useLobbySock(roomId!, nameConfirmed ? playerName : '');

  // Redirect when game launches
  useEffect(() => {
    if (launchedGameId) {
      navigate(`/game/${launchedGameId}`);
    }
  }, [launchedGameId, navigate]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chat.length]);

  // Determine own seat
  const mySeat = roomState?.seats.findIndex(
    (s) => s && !s.isAi && s.name === playerName,
  ) ?? -1;
  const isHost = mySeat === 0;

  if (!nameConfirmed) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg-base text-white">
        <div className="bg-bg-zone border border-border-zone rounded-lg p-6 w-80">
          <h2 className="text-lg font-semibold mb-3">Enter your name</h2>
          <input
            type="text"
            value={playerName}
            onChange={(e) => setPlayerName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && playerName.trim()) setNameConfirmed(true);
            }}
            className="w-full bg-bg-panel border border-border-zone rounded px-3 py-1.5 text-sm text-white mb-3 focus:outline-none focus:border-accent-blue"
            autoFocus
          />
          <button
            onClick={() => playerName.trim() && setNameConfirmed(true)}
            className="w-full bg-btn-primary border border-border-btn-primary text-white rounded px-4 py-2 text-sm font-medium hover:brightness-110"
          >
            Join Room
          </button>
        </div>
      </div>
    );
  }

  if (!roomState) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg-base text-white">
        Connecting to room...
      </div>
    );
  }

  const handleSendChat = () => {
    if (chatInput.trim()) {
      sendChat(chatInput.trim());
      setChatInput('');
    }
  };

  return (
    <div className="flex flex-col h-screen bg-bg-base text-white">
      {/* Header */}
      <div className="bg-bg-bar border-b border-border-sep px-4 py-2 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">{roomState.roomName}</h1>
          <span className="text-text-muted text-sm">Host: {roomState.host}</span>
        </div>
        {isSpectator && (
          <span className="text-text-muted text-xs bg-bg-panel px-2 py-1 rounded">
            SPECTATING
          </span>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Seat Grid */}
        <div className="flex-1 p-4">
          <div className="grid grid-cols-2 gap-3 max-w-lg">
            {[0, 1, 2, 3].map((seatIdx) => {
              const seat = roomState.seats[seatIdx];
              return (
                <div
                  key={seatIdx}
                  className="bg-bg-zone border border-border-zone rounded-lg p-4 min-h-[100px] flex flex-col items-center justify-center"
                >
                  {seat ? (
                    <>
                      <span className="text-sm font-medium">
                        {seat.isAi ? '🤖 AI' : seat.name}
                      </span>
                      <span className="text-xs text-text-muted mt-1">
                        Seat {seatIdx}
                      </span>
                      {!seat.isAi && (
                        <span
                          className={`text-xs mt-1 font-bold ${
                            seat.ready ? 'text-life-high' : 'text-life-med'
                          }`}
                        >
                          {seat.ready ? 'READY' : 'Not Ready'}
                        </span>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="text-text-muted text-sm">Waiting...</span>
                      <span className="text-xs text-text-muted mt-1">
                        Seat {seatIdx}
                      </span>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          {/* Action buttons */}
          {!isSpectator && (
            <div className="mt-4 flex gap-3">
              {mySeat >= 0 && (
                <button
                  onClick={() => sendReady(mySeat)}
                  className="bg-btn-primary border border-border-btn-primary text-white rounded px-4 py-2 text-sm font-medium hover:brightness-110"
                >
                  Toggle Ready
                </button>
              )}
              {isHost && (
                <button
                  onClick={async () => {
                    try {
                      const res = await fetch(`/api/v1/lobby/rooms/${roomId}/launch`, {
                        method: 'POST',
                      });
                      const data = await res.json();
                      if (data.gameId) {
                        navigate(`/game/${data.gameId}`);
                      }
                    } catch {
                      // launch via WS fallback
                      sendLaunch();
                    }
                  }}
                  className="bg-life-high border border-life-high text-white rounded px-4 py-2 text-sm font-bold hover:brightness-110"
                >
                  Launch Game
                </button>
              )}
            </div>
          )}
        </div>

        {/* Chat Panel */}
        <div className="w-[280px] bg-bg-panel border-l border-border-sep flex flex-col">
          <div className="px-3 py-2 border-b border-border-sep text-sm font-semibold">
            Chat
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {chat.map((msg: ChatMessage, i: number) => (
              <div key={i} className="text-[11px] leading-[1.4] break-words">
                <ChatBadge role={msg.role} />
                {msg.name && <span className="font-medium mr-1">{msg.name}:</span>}
                <span className="text-text-body">{msg.text}</span>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
          {!isSpectator && (
            <div className="border-t border-border-sep p-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSendChat();
                }}
                placeholder="Type a message..."
                className="w-full bg-bg-base border border-border-zone rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-accent-blue"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
