import type { ReactNode } from 'react'

export function EmptyState({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-10 text-center text-muted">
      <span>{title}</span>
      {action}
    </div>
  )
}
