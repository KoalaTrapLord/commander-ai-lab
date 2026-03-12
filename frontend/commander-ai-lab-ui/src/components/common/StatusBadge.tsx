import { CheckCircle, XCircle, AlertTriangle, Info } from 'lucide-react'

type Variant = 'success' | 'error' | 'warning' | 'info' | 'neutral'

interface StatusBadgeProps {
  variant: Variant
  label: string
  className?: string
}

const STYLES: Record<Variant, string> = {
  success: 'bg-status-success/15 text-status-success border-status-success/30',
  error: 'bg-status-error/15 text-status-error border-status-error/30',
  warning: 'bg-status-warning/15 text-status-warning border-status-warning/30',
  info: 'bg-status-info/15 text-status-info border-status-info/30',
  neutral: 'bg-bg-tertiary text-text-secondary border-border-primary',
}

const ICONS: Record<Variant, typeof CheckCircle> = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
  neutral: Info,
}

export function StatusBadge({ variant, label, className = '' }: StatusBadgeProps) {
  const Icon = ICONS[variant]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border ${STYLES[variant]} ${className}`}>
      <Icon className="w-3.5 h-3.5" />
      {label}
    </span>
  )
}
