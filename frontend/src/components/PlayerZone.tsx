import type { Player } from '../types/game';
import CardChip from './CardChip';

interface PlayerZoneProps {
  player: Player;
  isActive: boolean;
  isThinking: boolean;
  seatColour: string;
}

function lifeColor(life: number): string {
  if (life >= 30) return 'text-life-high';
  if (life >= 15) return 'text-life-med';
  return 'text-life-low';
}

export default function PlayerZone({ player, isActive, isThinking, seatColour }: PlayerZoneProps) {
  return (
    <div
      className={`bg-bg-zone border border-[#3a4060] rounded-md p-1.5 ${
        isThinking ? 'animate-pulse' : ''
      } ${player.eliminated ? 'opacity-40' : ''}`}
      style={isActive ? { borderColor: seatColour } : undefined}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] text-[#666]">
          P{player.seat}: {player.name}
        </span>
        <span className={`text-[28px] font-bold ${lifeColor(player.life)}`}>
          {player.life}
        </span>
      </div>
      <div className="flex flex-wrap gap-0.5">
        {player.battlefield.map((card, i) => (
          <CardChip key={i} card={card} />
        ))}
      </div>
    </div>
  );
}
