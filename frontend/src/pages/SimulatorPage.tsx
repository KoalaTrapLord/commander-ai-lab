import { useEffect, useRef, useState } from 'react';
import { SEAT_COLOURS } from '../constants';
import type { SimDeck, SimResult } from '../types/simulator';

const SEAT_LABELS = ['Seat 1 (You)', 'Seat 2', 'Seat 3', 'Seat 4'];

type SimStatus = 'idle' | 'running' | 'complete' | 'error';

export default function SimulatorPage() {
  // Deck list from API
  const [decks, setDecks] = useState<SimDeck[]>([]);
  const [loadingDecks, setLoadingDecks] = useState(true);

  // Slot selections (4 slots, null = empty)
  const [slots, setSlots] = useState<(number | null)[]>([null, null, null, null]);

  // Config
  const [numGames, setNumGames] = useState(10);
  const [engineType, setEngineType] = useState('heuristic');
  const [recordLogs, setRecordLogs] = useState(true);

  // Sim state
  const [simId, setSimId] = useState<string | null>(null);
  const [status, setStatus] = useState<SimStatus>('idle');
  const [completed, setCompleted] = useState(0);
  const [total, setTotal] = useState(0);
  const [result, setResult] = useState<SimResult | null>(null);
  const [games, setGames] = useState<unknown[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch decks on mount
  useEffect(() => {
    fetch('/api/decks')
      .then((res) => res.json())
      .then((data) => {
        const list = (data.decks || []).map((d: Record<string, unknown>) => ({
          id: d.id as number,
          name: d.name as string,
          commander_name: (d.commander_name || '') as string,
          color_identity: (d.color_identity || []) as string[],
        }));
        setDecks(list);
      })
      .catch(() => setDecks([]))
      .finally(() => setLoadingDecks(false));
  }, []);

  // Polling
  useEffect(() => {
    if (status !== 'running' || !simId) return;
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/sim/status?simId=${simId}`);
        const data = await res.json();
        setCompleted(data.completed ?? 0);
        setTotal(data.total ?? 0);
        if (data.status === 'complete') {
          setStatus('complete');
          // Fetch results
          const rres = await fetch(`/api/sim/result?simId=${simId}`);
          const rdata = await rres.json();
          setResult(rdata.summary ?? null);
          setGames(rdata.games ?? []);
        } else if (data.status === 'error') {
          setStatus('error');
          setError(data.error || 'Simulation failed');
        }
      } catch {
        // keep polling
      }
    }, 1000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status, simId]);

  const selectedCount = slots.filter((s) => s !== null).length;
  const canRun = selectedCount >= 2 && status !== 'running';

  const handleRun = async () => {
    const deckIds = slots.filter((s): s is number => s !== null);
    setStatus('running');
    setCompleted(0);
    setTotal(numGames);
    setResult(null);
    setGames([]);
    setError(null);

    try {
      const res = await fetch('/api/sim/run-n-player', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deckIds,
          numGames,
          recordLogs,
          engineType,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setStatus('error');
        setError(data.error || 'Failed to start simulation');
        return;
      }
      setSimId(data.simId);
      setTotal(data.total);
    } catch {
      setStatus('error');
      setError('Network error');
    }
  };

  const setSlot = (idx: number, value: number | null) => {
    setSlots((prev) => {
      const next = [...prev];
      next[idx] = value;
      return next;
    });
  };

  const getDeckById = (id: number) => decks.find((d) => d.id === id);

  return (
    <div className="min-h-screen bg-bg-base text-white p-6">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">Batch Simulator</h1>
        <p className="text-text-muted text-sm mb-6">
          Run N-player Monte Carlo simulations with your decks.
        </p>

        {/* Deck Selection */}
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Deck Slots</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {SEAT_LABELS.map((label, idx) => {
              const selected = slots[idx];
              const deck = selected !== null ? getDeckById(selected) : null;
              return (
                <div
                  key={idx}
                  className="bg-bg-zone rounded-md p-4"
                  style={{
                    border: `2px solid ${selected !== null ? SEAT_COLOURS[idx] : '#3a4060'}`,
                    boxShadow: selected !== null ? `0 0 8px ${SEAT_COLOURS[idx]}40` : 'none',
                  }}
                >
                  <div
                    className="text-sm font-medium mb-2"
                    style={{ color: SEAT_COLOURS[idx] }}
                  >
                    {label}
                  </div>
                  <select
                    value={selected ?? ''}
                    onChange={(e) => setSlot(idx, e.target.value ? Number(e.target.value) : null)}
                    className="w-full bg-bg-panel border border-border-zone rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
                  >
                    <option value="">— Empty —</option>
                    {decks.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                  {deck && (
                    <div className="mt-2 text-xs text-text-muted">
                      {deck.commander_name && (
                        <div className="truncate">{deck.commander_name}</div>
                      )}
                      {deck.color_identity.length > 0 && (
                        <div>{deck.color_identity.join(' ')}</div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {loadingDecks && (
            <p className="text-text-muted text-sm mt-2">Loading decks...</p>
          )}
        </div>

        {/* Config Row */}
        <div className="flex flex-wrap items-end gap-4 mb-6 bg-bg-zone rounded-md border border-border-zone p-4">
          <div>
            <label className="block text-sm text-text-muted mb-1">Games</label>
            <input
              type="number"
              min={1}
              max={1000}
              value={numGames}
              onChange={(e) => setNumGames(Math.max(1, Math.min(1000, Number(e.target.value))))}
              className="w-24 bg-bg-panel border border-border-zone rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
            />
          </div>
          <div>
            <label className="block text-sm text-text-muted mb-1">Engine</label>
            <select
              value={engineType}
              onChange={(e) => setEngineType(e.target.value)}
              className="bg-bg-panel border border-border-zone rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-accent-blue"
            >
              <option value="heuristic">Heuristic AI</option>
              <option value="deepseek">DeepSeek AI</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="recordLogs"
              checked={recordLogs}
              onChange={(e) => setRecordLogs(e.target.checked)}
              className="rounded"
            />
            <label htmlFor="recordLogs" className="text-sm text-text-muted">
              Record Logs
            </label>
          </div>
          <button
            onClick={handleRun}
            disabled={!canRun}
            className="bg-accent-blue text-white rounded px-4 py-2 text-sm font-medium hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {status === 'running' ? (
              <span className="flex items-center gap-2">
                <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Running...
              </span>
            ) : (
              'Run Simulation'
            )}
          </button>
        </div>

        {/* Progress */}
        {status === 'running' && (
          <div className="mb-6">
            <div className="flex justify-between text-sm text-text-muted mb-1">
              <span>Progress</span>
              <span>
                {completed} / {total} games
              </span>
            </div>
            <div className="w-full bg-bg-panel rounded-full h-3 overflow-hidden">
              <div
                className="h-full bg-accent-blue rounded-full transition-all duration-300"
                style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
              />
            </div>
          </div>
        )}

        {/* Error */}
        {status === 'error' && error && (
          <div className="mb-6 bg-red-900/30 border border-red-700 rounded-md p-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Results */}
        {status === 'complete' && result && (
          <div className="space-y-6">
            <div className="flex items-center gap-4 text-sm text-text-muted">
              <span>{result.totalGames} games</span>
              <span>{result.playerCount} players</span>
              <span>{result.elapsedSeconds}s elapsed</span>
            </div>

            {/* Win Rate Bar Chart */}
            <div className="bg-bg-zone rounded-md border border-border-zone p-4">
              <h3 className="text-sm font-semibold mb-3">Win Rates</h3>
              <div className="space-y-2">
                {result.players.map((p) => (
                  <div key={p.seat} className="flex items-center gap-3">
                    <div className="w-28 text-sm truncate" style={{ color: SEAT_COLOURS[p.seat] }}>
                      {p.deckName}
                    </div>
                    <div className="flex-1 bg-bg-panel rounded-full h-5 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${p.winRate}%`,
                          backgroundColor: SEAT_COLOURS[p.seat],
                          minWidth: p.winRate > 0 ? '2px' : '0',
                        }}
                      />
                    </div>
                    <div className="w-16 text-right text-sm font-mono">
                      {p.winRate}%
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Stats Table */}
            <div className="bg-bg-zone rounded-md border border-border-zone overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-zone text-text-muted">
                    <th className="text-left px-3 py-2">Seat</th>
                    <th className="text-left px-3 py-2">Deck</th>
                    <th className="text-right px-3 py-2">Wins</th>
                    <th className="text-right px-3 py-2">Win%</th>
                    <th className="text-right px-3 py-2">Avg Turns</th>
                    <th className="text-right px-3 py-2">Avg Dmg</th>
                    <th className="text-right px-3 py-2">Avg Spells</th>
                    <th className="text-right px-3 py-2">Avg Creatures</th>
                    <th className="text-right px-3 py-2">Avg Removal</th>
                  </tr>
                </thead>
                <tbody>
                  {result.players.map((p) => {
                    const isWinner = result.players.every((o) => o.wins <= p.wins);
                    return (
                      <tr
                        key={p.seat}
                        className={`border-b border-border-zone ${isWinner ? 'font-semibold' : ''}`}
                        style={{
                          backgroundColor: `${SEAT_COLOURS[p.seat]}${isWinner ? '20' : '0a'}`,
                        }}
                      >
                        <td className="px-3 py-2" style={{ color: SEAT_COLOURS[p.seat] }}>
                          P{p.seat + 1}
                        </td>
                        <td className="px-3 py-2">{p.deckName}</td>
                        <td className="text-right px-3 py-2">{p.wins}</td>
                        <td className="text-right px-3 py-2">{p.winRate}%</td>
                        <td className="text-right px-3 py-2">{p.avgTurns}</td>
                        <td className="text-right px-3 py-2">{p.avgDamageDealt}</td>
                        <td className="text-right px-3 py-2">{p.avgSpellsCast}</td>
                        <td className="text-right px-3 py-2">{p.avgCreaturesPlayed}</td>
                        <td className="text-right px-3 py-2">{p.avgRemovalUsed}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Per-Game Logs (collapsible) */}
            {games.length > 0 && (
              <div className="bg-bg-zone rounded-md border border-border-zone">
                <button
                  onClick={() => setShowLogs(!showLogs)}
                  className="w-full text-left px-4 py-3 text-sm font-medium flex justify-between items-center hover:bg-bg-panel transition-colors"
                >
                  <span>Per-Game Results ({games.length} games)</span>
                  <span className="text-text-muted">{showLogs ? '▲' : '▼'}</span>
                </button>
                {showLogs && (
                  <div className="px-4 pb-3 max-h-96 overflow-y-auto">
                    <div className="space-y-1">
                      {games.map((g: unknown, i: number) => {
                        const game = g as Record<string, unknown>;
                        return (
                          <div
                            key={i}
                            className="flex items-center gap-3 text-xs text-text-muted py-1 border-b border-border-zone"
                          >
                            <span className="w-12 font-mono">#{game.gameNumber as number}</span>
                            <span>
                              Winner:{' '}
                              <span
                                style={{
                                  color: SEAT_COLOURS[(game.winner ?? game.winningSeat ?? 0) as number],
                                }}
                              >
                                P{((game.winner ?? game.winningSeat ?? 0) as number) + 1}
                              </span>
                            </span>
                            <span>{game.turns as number} turns</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
