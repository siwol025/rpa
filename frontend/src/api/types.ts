/*
 * 기준: 백엔드 backend/docs/api/convention.md v0.1 (API 규약), openapi.json, architecture.md §5·§7.
 * 목록·상세(GET /calls, GET /calls/{id}), 통계(GET /stats/summary, /trend, /breakdown), 업로드(POST /uploads),
 * 수정·검토 완료(PATCH), 삭제(DELETE), 재처리(POST retry), 음성(GET audio)은 openapi.json과 대조했다 (main e9490fc).
 * 엑셀(GET /reports/excel)은 파일(blob)로 받으므로 여기에 응답 타입이 없다 (api/stats.ts fetchExcel).
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
  /** 서버가 계산: 처리 중 상태로 정체 기준 시간을 넘김 */
  is_stale: boolean
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

/** 보낸 값만 바꾼다. null은 비우기 (빈 글자는 422) */
export interface CallPatch {
  category?: Category
  question_summary?: string | null
  action_summary?: string | null
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
export const SUMMARY_MAX_LENGTH = 2000
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

/** total과 by_category만 기간을 따르고, 나머지는 기간과 무관한 전체 건수 (규약 §4.3) */
export interface StatsSummary {
  total: number
  by_category: Record<string, number>
  action_open: number
  needs_review: number
  metadata_incomplete: number
  failed: number
  stale: number
}

/** POST /uploads. name: 저장된 이름 (등록 후 목록의 original_name) */
export interface UploadResult {
  items: { name: string }[]
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
