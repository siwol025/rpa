import { CATEGORIES, type ActionStatus, type CallStatus, type Category } from '../api/types'

export type StatusTone = 'running' | 'done' | 'review' | 'failed' | 'warn'

export const STATUS_LABEL: Record<CallStatus, string> = {
  REGISTERED: '등록됨',
  QUEUED: '처리 대기',
  STT_DONE: '전사 완료',
  STORED: '저장 완료',
  NEEDS_REVIEW: '검토 필요',
  FAILED: '실패',
  RETRY_REQUESTED: '재처리 요청됨',
}

export function statusTone(status: CallStatus): StatusTone {
  if (status === 'STORED') return 'done'
  if (status === 'NEEDS_REVIEW') return 'review'
  if (status === 'FAILED') return 'failed'
  return 'running'
}

/** 재처리 요청이 허용되는 상태 (architecture.md §5) */
export function canRetry(status: CallStatus, stale: boolean): boolean {
  if (status === 'FAILED' || status === 'NEEDS_REVIEW' || status === 'STORED') return true
  return stale && status !== 'RETRY_REQUESTED'
}

const CATEGORY_LABEL: Record<Category, string> = {
  INQUIRY: '질의',
  COMPLAINT: '불만',
  SUGGESTION: '건의',
  EDUCATION: '교육 내용',
  ETC: '기타 문의',
}

/** 나중에 추가된 유형이면 코드를 그대로 보여준다 */
export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category as Category] ?? category
}

export function categoryColorVar(category: string): string {
  const i = (CATEGORIES as readonly string[]).indexOf(category)
  return i < 0 ? 'var(--line-strong)' : `var(--s${i + 1})`
}

export const ACTION_LABEL: Record<ActionStatus, string> = { OPEN: '미조치', DONE: '조치 완료' }

export function actionLabel(status: ActionStatus | null): string {
  return status ? (ACTION_LABEL[status] ?? status) : '-'
}

export const STEP_LABEL: Record<string, string> = {
  REGISTER: '등록',
  QUEUE: '대기열',
  STT: '전사',
  GENAI: 'AI 분석',
  STORE: '저장',
  EXCEL: '엑셀',
  CRM: 'CRM',
  RETRY: '재처리',
}
