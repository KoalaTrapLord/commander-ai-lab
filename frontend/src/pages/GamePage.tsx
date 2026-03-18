import { useParams } from 'react-router-dom';
import { useGameSocket } from '../hooks/useGameSocket';
import PhaseBar from '../components/PhaseBar';
import Board from '../components/Board';
import NarrationPanel from '../components/NarrationPanel';
import MoveBar from '../components/MoveBar';
import GameOverOverlay from '../components/GameOverOverlay';

export default function GamePage() {
  const { gameId } = useParams<{ gameId: string }>();
  const { gameState, narration, thinking, hand, gameOver, status, sendMove, sendConcede } =
    useGameSocket(gameId!);

  if (!gameState) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg-base text-white">
        Connecting…
      </div>
    );
  }

  const winnerPlayer = gameOver
    ? gameState.players.find((p) => p.seat === gameOver.winner) ?? null
    : null;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg-base text-white">
      <PhaseBar
        phase={gameState.current_phase}
        activeSeat={gameState.active_seat}
        players={gameState.players}
      />
      <div className="flex flex-1 overflow-hidden">
        <Board gameState={gameState} thinkingSeats={thinking} />
        <NarrationPanel lines={narration} thinkingSeats={thinking} />
      </div>
      <MoveBar
        hand={hand}
        humanSeat={0}
        onPass={() => sendMove('pass')}
        onConcede={sendConcede}
        onPlayCard={(index) => sendMove('play_card', { index })}
        status={status}
      />
      <GameOverOverlay
        show={gameOver !== null}
        winner={winnerPlayer}
        reason={gameOver?.reason ?? ''}
        players={gameState.players}
      />
    </div>
  );
}
