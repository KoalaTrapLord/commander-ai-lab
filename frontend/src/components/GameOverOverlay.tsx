import type { Player } from '../types/game';
import { SEAT_COLOURS } from '../constants';

interface GameOverOverlayProps {
  show: boolean;
  winner: Player | null;
  reason: string;
  players: Player[];
}

export default function GameOverOverlay({ show, winner, reason, players }: GameOverOverlayProps) {
  if (!show) return null;

  return (
    <div className="fixed inset-0 bg-black/80 z-[100] flex items-center justify-center">
      <div className="bg-bg-zone border-2 border-[#4060c0] rounded-[10px] px-[60px] py-10 text-center">
        {winner && (
          <h2
            className="text-4xl font-bold"
            style={{ color: SEAT_COLOURS[winner.seat] }}
          >
            {winner.name} Wins!
          </h2>
        )}
        <p className="text-base text-[#aaa] mt-2">{reason}</p>
        <ul className="mt-6 space-y-1">
          {players.map((p) => (
            <li key={p.seat} className="text-sm">
              <span style={{ color: SEAT_COLOURS[p.seat] }}>P{p.seat}</span>{' '}
              {p.name} — {p.life} life
              {p.eliminated && (
                <span className="text-red-500 ml-1 font-bold">[ELIM]</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
