import { categoryColorVar } from '../lib/status'

export function CategoryChip({ category }: { category: string | null }) {
  if (!category) return <span className="text-muted">-</span>
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-surface-2 py-0.5 pr-2.5 pl-2 text-xs font-medium">
      <i aria-hidden="true" className="size-2 rounded-full" style={{ background: categoryColorVar(category) }} />
      {category}
    </span>
  )
}
