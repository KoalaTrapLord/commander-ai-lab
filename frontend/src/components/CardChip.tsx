import type { Card } from '../types/game';

interface CardChipProps {
  card: Card;
  onClick?: () => void;
}

export default function CardChip({ card, onClick }: CardChipProps) {
  return (
    <span
      onClick={onClick}
      className={`bg-card-bg border border-[#444] rounded text-[10px] max-w-[110px] overflow-hidden text-ellipsis whitespace-nowrap cursor-pointer px-1.5 py-0.5 hover:border-[#ffdc32] ${
        card.tapped ? 'opacity-55 italic' : ''
      }`}
    >
      {card.name}
      {card.is_commander && <span className="text-[#ffd200]"> ★</span>}
    </span>
  );
}
