export interface SimDeck {
  id: number;
  name: string;
  commander_name: string;
  color_identity: string[];
}

export interface SimPlayerResult {
  seat: number;
  deckName: string;
  wins: number;
  winRate: number;
  avgTurns: number;
  avgDamageDealt: number;
  avgSpellsCast: number;
  avgCreaturesPlayed: number;
  avgRemovalUsed: number;
  avgRampPlayed: number;
  avgCardsDrawn: number;
  avgMaxBoardSize: number;
}

export interface SimResult {
  playerCount: number;
  totalGames: number;
  players: SimPlayerResult[];
  elapsedSeconds: number;
}
