import { useRef, useEffect, useState } from 'react';
import type { NarrationLine } from '../types/game';
import { SEAT_COLOURS } from '../constants';

interface NarrationPanelProps {
  lines: NarrationLine[];
  thinkingSeats: Set<number>;
}

export default function NarrationPanel({ lines, thinkingSeats }: NarrationPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dots, setDots] = useState('.');

  // Auto-scroll on new lines
  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  // Cycling dots for thinking animation
  useEffect(() => {
    if (thinkingSeats.size === 0) return;
    const interval = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? '.' : prev + '.'));
    }, 500);
    return () => clearInterval(interval);
  }, [thinkingSeats.size]);

  const displayed = lines.slice(-120);

  return (
    <div
      ref={containerRef}
      className="w-[260px] bg-bg-panel border-l border-[#2a2e48] overflow-y-auto p-2 flex flex-col"
    >
      {displayed.map((line, i) => {
        let colorClass = 'text-[#e8e8e8]';
        let style: React.CSSProperties | undefined;

        if (line.isSystem) {
          colorClass = 'text-[#556]';
        } else if (line.seat !== undefined) {
          colorClass = '';
          style = { color: SEAT_COLOURS[line.seat] };
        }

        return (
          <div
            key={i}
            className={`text-[11px] leading-[1.4] break-words ${colorClass}`}
            style={style}
          >
            {line.text}
          </div>
        );
      })}
      {thinkingSeats.size > 0 &&
        Array.from(thinkingSeats).map((seat) => (
          <div
            key={`thinking-${seat}`}
            className="text-[11px] leading-[1.4] break-words text-accent-think italic"
          >
            P{seat} thinking{dots}
          </div>
        ))}
    </div>
  );
}
