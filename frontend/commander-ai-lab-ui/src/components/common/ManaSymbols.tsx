// Parse MTG mana cost strings like "{2}{W}{U}" into colored symbols

const MANA_COLORS: Record<string, string> = {
  W: 'bg-mana-white text-black',
  U: 'bg-mana-blue text-white',
  B: 'bg-mana-black text-white',
  R: 'bg-mana-red text-white',
  G: 'bg-mana-green text-white',
  C: 'bg-mana-colorless text-white',
}

interface ManaSymbolsProps {
  cost: string
  size?: 'sm' | 'md'
}

export function ManaSymbols({ cost, size = 'sm' }: ManaSymbolsProps) {
  if (!cost) return null

  const symbols = cost.match(/\{([^}]+)\}/g)
  if (!symbols) return <span className="text-text-tertiary">{cost}</span>

  const sz = size === 'sm' ? 'w-5 h-5 text-[10px]' : 'w-6 h-6 text-xs'

  return (
    <span className="inline-flex items-center gap-0.5">
      {symbols.map((s, i) => {
        const val = s.replace(/[{}]/g, '')
        const colorClass = MANA_COLORS[val] || 'bg-mana-colorless text-white'
        return (
          <span
            key={i}
            className={`${sz} inline-flex items-center justify-center rounded-full font-bold ${colorClass}`}
          >
            {val}
          </span>
        )
      })}
    </span>
  )
}

// Color identity dots
interface ColorDotsProps {
  colors: string[]
  size?: 'sm' | 'md'
}

export function ColorDots({ colors, size = 'sm' }: ColorDotsProps) {
  if (!colors || colors.length === 0) return <span className="text-text-tertiary text-xs">Colorless</span>

  const sz = size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'

  const DOT_COLORS: Record<string, string> = {
    W: 'bg-mana-white',
    U: 'bg-mana-blue',
    B: 'bg-mana-black border border-border-secondary',
    R: 'bg-mana-red',
    G: 'bg-mana-green',
  }

  return (
    <span className="inline-flex items-center gap-0.5">
      {colors.map(c => (
        <span key={c} className={`${sz} rounded-full ${DOT_COLORS[c] || 'bg-mana-colorless'}`} />
      ))}
    </span>
  )
}
