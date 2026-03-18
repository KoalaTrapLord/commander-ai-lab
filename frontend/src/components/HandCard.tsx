import type { Card } from '../types/game';

interface HandCardProps {
  card: Card;
  index: number;
  isSelected: boolean;
  onClick: () => void;
}

export default function HandCard({ card, isSelected, onClick }: HandCardProps) {
  return (
    <button
      onClick={onClick}
      className={`rounded text-[11px] px-2 py-1 cursor-pointer ${
        isSelected
          ? 'border border-[#ffdc32] bg-card-selected'
          : 'bg-card-hand border border-[#5060a0]'
      }`}
    >
      {card.name}
    </button>
  );
}
