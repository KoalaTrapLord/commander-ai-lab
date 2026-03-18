import type { Phase } from './types/game';

export const SEAT_COLOURS = ['#4696ff', '#ff6450', '#50d278', '#dcaa32'] as const;

export const PHASES: Phase[] = [
  'untap', 'upkeep', 'draw', 'main1',
  'begin_combat', 'declare_attackers', 'declare_blockers', 'combat_damage',
  'main2', 'end_step', 'cleanup',
];
