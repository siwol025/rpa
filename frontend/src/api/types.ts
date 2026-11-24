/*
 * 백엔드 문서(research.md §4·§5, architecture.md §5·§7, prd.md §6)의 이름을 그대로 쓴다.
 *
 * [확인 필요] 문서에 세부 형태가 없어 임시로 정한 것. 회신이 다르면 여기와 src/mocks/, 그 값을 쓰는 화면을 고친다.
 *  1. 목록 항목과 상세 응답의 구조(아래 CallListItem, CallDetail), 응답의 stale 값
 *  2. 검토 완료를 알리는 필드(CallPatch.review_completed)
 *  3. 통계 응답의 구조(StatsSummary, TrendItem, BreakdownItem)
 *  4. sort 값의 형식
 *  5. 유형 값이 한글인지 코드(INQUIRY 등)인지
 */

export const CATEGORIES = ['질의', '불만', '건의', '교육 내용', '기타 문의'] as const
export type Category = (typeof CATEGORIES)[number]

export const STATUSES = ['REGISTERED', 'QUEUED', 'STT_DONE', 'STORED', 'NEEDS_REVIEW', 'FAILED', 'RETRY_REQUESTED'] as const
export type CallStatus = (typeof STATUSES)[number]

export const ACTION_STATUSES = ['OPEN', 'DONE'] as const
export type ActionStatus = (typeof ACTION_STATUSES)[number]

export interface CallBase {
  id: number
  source_type: 'DRIVE' | 'WEB'
  original_name: string
  duration_sec: number | null
  agent_name: string | null
  client_company: string | null
  call_datetime: string | null
  metadata_incomplete: boolean
  status: CallStatus
  status_changed_at: string
  retry_count: number
  stale: boolean
}

export interface CallListItem extends CallBase {
  category: Category | null
  question_summary: string | null
  action_status: ActionStatus | null
}

export interface Segment {
  speaker: 'AGENT' | 'CUSTOMER'
  start: number
  end: number
  text: string
}

export interface Entities {
  client_company?: string
  products?: string[]
  dates?: string[]
  keywords?: string[]
}

export interface Analysis {
  category: Category
  confidence: number | null
  question_summary: string | null
  action_summary: string | null
  follow_up_required: boolean
  action_status: ActionStatus
  entities: Entities | null
  needs_review: boolean
}

export interface ProcessingLog {
  step: string
  status: 'SUCCESS' | 'FAIL' | 'RETRY'
  message: string | null
  created_at: string
}

export interface CallDetail extends CallBase {
  transcript: { segments: Segment[] } | null
  analysis: Analysis | null
  processing_log: ProcessingLog[]
}

export interface CallPatch {
  category?: Category
  question_summary?: string
  action_summary?: string
  action_status?: ActionStatus
  agent_name?: string | null
  client_company?: string | null
  call_datetime?: string | null
  review_completed?: true
  editor?: string
}

export interface Page<T> {
  items: T[]
  page: number
  size: number
  total: number
}

export type CallSort = 'call_datetime:desc' | 'call_datetime:asc'

export interface CallListParams {
  from?: string
  to?: string
  category?: Category
  agent?: string
  client?: string
  status?: CallStatus
  q?: string
  stale?: boolean
  metadata_incomplete?: boolean
  page: number
  size: number
  sort?: CallSort
}

export interface Period {
  from?: string
  to?: string
}

export interface StatsSummary {
  total: number
  by_category: Record<Category, number>
  action_open: number
  needs_review: number
  metadata_incomplete: number
  failed: number
  stale: number
}

export type Granularity = 'day' | 'week' | 'month'

/** period: 구간의 시작일 YYYY-MM-DD (주는 월요일, 월은 1일) */
export interface TrendItem {
  period: string
  count: number
}

export interface BreakdownItem {
  name: string
  count: number
}
