/*
 * 기준: 백엔드 backend/docs/api/convention.md v0.1 (API 규약), openapi.json, architecture.md §5·§7.
 * 목록·상세(GET /calls, GET /calls/{id})와 통계 추이·분류(GET /stats/trend, /stats/breakdown)는 openapi.json과 대조했다 (main 7e3eab1).
 *
 * [확인 필요] 아직 API가 없어 임시로 정한 것. 회신이 다르면 여기와 src/mocks/, 그 값을 쓰는 화면을 고친다.
 *  1. 검토 완료를 알리는 필드(CallPatch.review_completed)
 *  2. 통계 요약 응답의 필드(StatsSummary)
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
  created_at: string
  /** 정체 감지(R-11)가 생기기 전에는 응답에 없다 */
  is_stale?: boolean
}

export interface CallListItem extends CallBase {
  category: Category | null
  question_summary: string | null
  action_status: ActionStatus | null
}

export interface Segment {
  speaker: 'AGENT' | 'CUSTOMER' | 'UNKNOWN'
  start_sec: number
  end_sec: number
  text: string
}

/** type: PRODUCT, ORG, DATE, AMOUNT, REF_NO, OTHER. 나중에 늘어날 수 있다 */
export interface Entity {
  type: string
  value: string
}

export interface Analysis {
  category: Category
  confidence: number | null
  question_summary: string | null
  action_summary: string | null
  follow_up_required: boolean | null
  action_status: ActionStatus | null
  entities: Entity[] | null
  needs_review: boolean | null
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
export const Q_MAX_LENGTH = 100
export const DATE_MIN = '2000-01-01'
export const DATE_MAX = '2100-12-31'

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

/** name: 담당자·고객사가 없는 상담을 묶은 행은 null (맨 뒤). by_category: 분석 전인 상담은 빠진다 */
export interface BreakdownItem {
  name: string | null
  count: number
  by_category: Record<Category, number>
}
