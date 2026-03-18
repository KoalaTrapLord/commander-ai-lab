import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

interface RoomSummary {
  roomId: string;
  name: string;
  host: string;
  playerCount: number;
}

export default function LobbyPage() {
  const navigate = useNavigate();
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [loading, setLoading] = useState(true);

  // Create room form state
  const [roomName, setRoomName] = useState('');
  const [hostName, setHostName] = useState('');
  const [aiSlots, setAiSlots] = useState(0);
  const [password, setPassword] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetch('/api/v1/lobby/rooms')
      .then((res) => res.json())
      .then((data) => setRooms(data))
      .catch(() => setRooms([]))
      .finally(() => setLoading(false));
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      const res = await fetch('/api/v1/lobby/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: roomName,
          host: hostName,
          ai_slots: aiSlots,
          password: password || undefined,
        }),
      });
      const data = await res.json();
      navigate(`/room/${data.roomId}?name=${encodeURIComponent(hostName)}`);
    } catch {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-base text-white p-6">
      <h1 className="text-3xl font-bold mb-6">Commander AI Lab — Lobby</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl">
        {/* Room List */}
        <div className="bg-bg-zone rounded-lg border border-border-zone p-4">
          <h2 className="text-lg font-semibold mb-3">Open Rooms</h2>
          {loading ? (
            <p className="text-text-muted text-sm">Loading...</p>
          ) : rooms.length === 0 ? (
            <p className="text-text-muted text-sm">No rooms available. Create one!</p>
          ) : (
            <ul className="space-y-2">
              {rooms.map((room) => (
                <li key={room.roomId}>
                  <button
                    onClick={() => navigate(`/room/${room.roomId}`)}
                    className="w-full text-left bg-bg-panel border border-border-zone rounded px-3 py-2 hover:border-accent-blue transition-colors"
                  >
                    <span className="font-medium">{room.name}</span>
                    <span className="text-text-muted text-sm ml-2">
                      Host: {room.host} · {room.playerCount}/4 players
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Create Room Form */}
        <div className="bg-bg-zone rounded-lg border border-border-zone p-4">
          <h2 className="text-lg font-semibold mb-3">Create Room</h2>
          <form onSubmit={handleCreate} className="space-y-3">
            <div>
              <label className="block text-sm text-text-muted mb-1">Room Name</label>
              <input
                type="text"
                value={roomName}
                onChange={(e) => setRoomName(e.target.value)}
                required
                className="w-full bg-bg-panel border border-border-zone rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
              />
            </div>
            <div>
              <label className="block text-sm text-text-muted mb-1">Your Name</label>
              <input
                type="text"
                value={hostName}
                onChange={(e) => setHostName(e.target.value)}
                required
                className="w-full bg-bg-panel border border-border-zone rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
              />
            </div>
            <div>
              <label className="block text-sm text-text-muted mb-1">AI Players</label>
              <select
                value={aiSlots}
                onChange={(e) => setAiSlots(Number(e.target.value))}
                className="w-full bg-bg-panel border border-border-zone rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
              >
                <option value={0}>0 AI players</option>
                <option value={1}>1 AI player</option>
                <option value={2}>2 AI players</option>
                <option value={3}>3 AI players</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-text-muted mb-1">Password (optional)</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-bg-panel border border-border-zone rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
              />
            </div>
            <button
              type="submit"
              disabled={creating}
              className="w-full bg-btn-primary border border-border-btn-primary text-white rounded px-4 py-2 text-sm font-medium hover:brightness-110 disabled:opacity-50"
            >
              {creating ? 'Creating...' : 'Create Room'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
