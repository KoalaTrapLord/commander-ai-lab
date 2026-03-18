import type { GameState } from '../types/game';
import { SEAT_COLOURS } from '../constants';
import PlayerZone from './PlayerZone';
import CardChip from './CardChip';

interface BoardProps {
  gameState: GameState;
  thinkingSeats: Set<number>;
}

export default function Board({ gameState, thinkingSeats }: BoardProps) {
  const { players, active_seat, stack } = gameState;

  const getPlayer = (seat: number) => players.find((p) => p.seat === seat);

  const renderZone = (seat: number, className: string) => {
    const player = getPlayer(seat);
    if (!player) return <div className={className} />;
    return (
      <div className={className}>
        <PlayerZone
          player={player}
          isActive={active_seat === seat}
          isThinking={thinkingSeats.has(seat)}
          seatColour={SEAT_COLOURS[seat]}
        />
      </div>
    );
  };

  return (
    <div className="grid grid-cols-[180px_1fr_180px] grid-rows-3 gap-1 flex-1">
      {/* Row 1: P1 (top-left), stack center, P2 (top-right) */}
      {renderZone(1, 'row-start-1 col-start-1')}
      <div className="bg-bg-zone border border-accent-purple rounded-md min-h-[60px] row-span-3 col-start-2 p-2 overflow-y-auto">
        <span className="text-[10px] text-[#666] block mb-1">Stack</span>
        <div className="flex flex-wrap gap-0.5">
          {stack.map((card, i) => (
            <CardChip key={i} card={card} />
          ))}
        </div>
      </div>
      {renderZone(2, 'row-start-1 col-start-3')}

      {/* Row 2: empty side cells (stack spans all 3 rows in center) */}
      <div className="row-start-2 col-start-1" />
      <div className="row-start-2 col-start-3" />

      {/* Row 3: P0 (bottom-left), P3 (bottom-right) */}
      {renderZone(0, 'row-start-3 col-start-1')}
      {renderZone(3, 'row-start-3 col-start-3')}
    </div>
  );
}
