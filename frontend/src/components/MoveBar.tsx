import { useState } from 'react';
import type { Card } from '../types/game';
import HandCard from './HandCard';

interface MoveBarProps {
  hand: Card[];
  humanSeat: number;
  onPass: () => void;
  onConcede: () => void;
  onPlayCard: (index: number) => void;
  status: string;
}

export default function MoveBar({ hand, onPass, onConcede, onPlayCard, status }: MoveBarProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const handleCardClick = (index: number) => {
    if (selectedIndex === index) {
      onPlayCard(index);
      setSelectedIndex(null);
    } else {
      setSelectedIndex(index);
    }
  };

  return (
    <div className="bg-bg-bar border-t border-[#2a2e48] px-2.5 py-1.5 flex items-center gap-2">
      <button
        onClick={onPass}
        className="bg-[#2a5090] border border-[#4080d0] text-white rounded px-3 py-1 text-sm cursor-pointer hover:brightness-110"
      >
        Pass Priority
      </button>
      <button
        onClick={() => {
          if (window.confirm('Are you sure you want to concede?')) onConcede();
        }}
        className="bg-[#2a3868] border border-[#4060a0] text-white rounded px-3 py-1 text-sm cursor-pointer"
      >
        Concede
      </button>
      {hand.map((card, i) => (
        <HandCard
          key={i}
          card={card}
          index={i}
          isSelected={selectedIndex === i}
          onClick={() => handleCardClick(i)}
        />
      ))}
      <span className="text-[11px] text-[#778] ml-auto">{status}</span>
    </div>
  );
}
