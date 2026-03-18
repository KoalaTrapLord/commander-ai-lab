import type { Phase, Player } from '../types/game';
import { PHASES, SEAT_COLOURS } from '../constants';

interface PhaseBarProps {
  phase: Phase;
  activeSeat: number;
  players: Player[];
}

export default function PhaseBar({ phase, activeSeat, players }: PhaseBarProps) {
  const activePlayer = players.find((p) => p.seat === activeSeat);

  return (
    <div className="h-[34px] bg-[#1e2338] px-2 py-1 flex items-center gap-1">
      {PHASES.map((p) => (
        <button
          key={p}
          className={`text-[11px] rounded px-2 py-0.5 ${
            p === phase
              ? 'bg-accent-blue text-white'
              : 'bg-[#252a42] text-[#888]'
          }`}
        >
          {p}
        </button>
      ))}
      {activePlayer && (
        <span
          className="text-[11px] ml-auto font-bold"
          style={{ color: SEAT_COLOURS[activeSeat] }}
        >
          P{activeSeat}: {activePlayer.name}
        </span>
      )}
    </div>
  );
}
