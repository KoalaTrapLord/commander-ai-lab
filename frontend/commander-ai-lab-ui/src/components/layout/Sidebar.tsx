import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/',           label: 'Batch Sim',   icon: '⚗️' },
  { to: '/collection', label: 'Collection',  icon: '📦' },
  { to: '/decks',      label: 'Decks',       icon: '🃏' },
  { to: '/autogen',    label: 'Auto Gen',    icon: '⚡' },
  { to: '/simulator',  label: 'Simulator',   icon: '🎮' },
  { to: '/coach',      label: 'Coach',       icon: '🧠' },
  { to: '/training',   label: 'Training',    icon: '📈' },
]

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 bottom-0 w-56 bg-bg-secondary border-r border-border-primary flex flex-col z-30">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border-primary">
        <h1 className="text-base font-bold text-text-primary tracking-tight">
          Commander AI Lab
        </h1>
        <p className="text-xs text-text-tertiary mt-0.5">MTG Intelligence Platform</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 overflow-y-auto">
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-2.5 text-sm transition-colors duration-150 ${
                isActive
                  ? 'bg-accent-blue/10 text-accent-blue border-r-2 border-accent-blue'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
              }`
            }
          >
            <span className="text-base">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border-primary">
        <p className="text-xs text-text-tertiary">v4.0 — React + TypeScript</p>
      </div>
    </aside>
  )
}
