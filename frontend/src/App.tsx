import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import LobbyPage from './pages/LobbyPage';
import RoomPage from './pages/RoomPage';
import GamePage from './pages/GamePage';
import SimulatorPage from './pages/SimulatorPage';

function Nav() {
  const location = useLocation();
  // Hide nav on active game pages
  if (location.pathname.startsWith('/game/')) return null;
  const links = [
    { to: '/', label: 'Lobby' },
    { to: '/simulator', label: 'Simulator' },
  ];
  return (
    <nav className="bg-bg-bar border-b border-border-zone px-4 py-2 flex items-center gap-4">
      <span className="text-sm font-bold text-white mr-4">Commander AI Lab</span>
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          className={`text-sm px-2 py-1 rounded transition-colors ${
            location.pathname === l.to
              ? 'text-white bg-accent-blue/20'
              : 'text-text-muted hover:text-white'
          }`}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<LobbyPage />} />
        <Route path="/room/:roomId" element={<RoomPage />} />
        <Route path="/game/:gameId" element={<GamePage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
      </Routes>
    </BrowserRouter>
  );
}
export default App;
