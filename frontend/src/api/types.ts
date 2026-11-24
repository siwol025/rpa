/*
 * 기준: 백엔드 backend/docs/api/convention.md v0.1 (API 규약), research.md §4·§5, architecture.md §5·§7.
 * 엔드포인트별 필드의 최종 기준은 openapi.json인데 아직 비어 있다(paths: {}). 채워지면 이 파일과 대조한다.
 *
 * [확인 필요] 규약에 없어 임시로 정한 것. 회신이 다르면 여기와 src/mocks/, 그 값을 쓰는 화면을 고친다.
 *  1. 목록 항목에 들어가는 필드(CallListItem), 상세 응답의 구조와 로그의 이름(processing_log)
 *  2. 상세 응답에도 is_stale이 있는지
 *  3. 검토 완료를 알리는 필드(CallPatch.review_completed)
 *  4. 통계 응답의 필드(StatsSummary, TrendItem, BreakdownItem)
 */

export const CATEGORIES = ['INQUIRY', 'COMPLAINT', 'SUGGESTION', 'EDUCATION', 'ETC'] as const
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
  is_stale: boolean
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

/** POST /calls/{id}/retry */
export interface RetryResult {
  call_id: number
  status: CallStatus
  retry_count: number
}

export const PAGE_MAX = 10_000
export const PAGE_SIZE_MAX = 100

export interface Page<T> {
  items: T[]
  page: number
  size: number
  total: number
}

/** 내림차순은 앞에 - */
export type CallSort = 'call_datetime' | '-call_datetime' | 'created_at' | '-created_at' | 'status_changed_at' | '-status_changed_at'

export interface CallListParams {
  from?: string
  to?: string
  category?: Category
  agent?: string
  client?: string
  status?: CallStatus | CallStatus[]
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
  by_category: Record<string, number>
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
