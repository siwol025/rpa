import type { ReactNode } from 'react'
import type { CallBase } from '../api/types'
import { STATUS_LABEL, statusTone, type StatusTone } from '../lib/status'

const TONE_CLASS: Record<StatusTone, string> = {
  running: 'text-fg-2 bg-surface-2',
  done: 'text-good bg-good-bg',
  review: 'text-review bg-review-bg',
  failed: 'text-crit bg-crit-bg',
  warn: 'text-warn bg-warn-bg',
}

const ICON: Record<StatusTone, string> = {
  running: 'M6 3.6V6l1.6 1M10.2 6a4.2 4.2 0 1 1-8.4 0 4.2 4.2 0 0 1 8.4 0Z',
  done: 'M2.5 6.2l2.3 2.3 4.7-5',
  review: 'M6 2.5v4.2M6 9v.2',
  failed: 'M3 3l6 6M9 3l-6 6',
  warn: 'M6 2l4.5 8h-9zM6 5.2v2M6 8.6v.1',
}

export function Badge({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}>
      <svg aria-hidden="true" viewBox="0 0 12 12" className="size-3 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d={ICON[tone]} />
      </svg>
      <span className="min-w-0">{children}</span>
    </span>
  )
}

type BadgeFields = Pick<CallBase, 'status' | 'is_stale' | 'metadata_incomplete'>

/** 처리 상태 + 정체 + 메타데이터 확인 필요 */
export function StatusBadges({ call, metadata = true }: { call: BadgeFields; metadata?: boolean }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      <Badge tone={statusTone(call.status)}>{STATUS_LABEL[call.status] ?? call.status}</Badge>
      {call.is_stale && <Badge tone="warn">정체</Badge>}
      {metadata && call.metadata_incomplete && <Badge tone="warn">메타데이터 확인 필요</Badge>}
    </span>
  )
}
