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

/** 재처리 요청이 허용되는 상태 (architecture.md §5). 정체 여부를 모르면 정체가 아닌 것으로 본다 */
export function canRetry(status: CallStatus, stale = false): boolean {
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

/** 개체명 종류 (stt/schema/call_schema.json). 보여주는 순서 */
export const ENTITY_LABEL: Record<string, string> = {
  PRODUCT: '제품·서비스',
  ORG: '기관·회사',
  DATE: '일정',
  AMOUNT: '금액',
  REF_NO: '접수 번호',
  OTHER: '기타',
}

const ACTOR_LABEL: Record<string, string> = { robot: '로봇', web: '웹' }

/** 실패한 단계 (stt/schema/call_schema.json의 error.stage) */
const STAGE_LABEL: Record<string, string> = {
  INPUT: '입력',
  STT: '전사',
  PII: '개인정보 가리기',
  GENAI: 'AI 분석',
  VALIDATION: '결과 검증',
}

/** "[STT] 사유" → "전사: 사유". 모르는 단계는 그대로 */
function stageText(text: string): string {
  const m = /^\[([A-Z]+)\]\s*([\s\S]*)$/.exec(text)
  const label = m && STAGE_LABEL[m[1]]
  if (!label) return text
  return m[2] ? `${label}: ${m[2]}` : label
}

/** 서버가 남긴 "[robot] QUEUED -> STT_DONE: 사유" 형식을 한글로 바꾼다. 다른 형식은 그대로 */
export function logMessage(message: string | null): string {
  const m = /^\[(robot|web)\]\s*([\s\S]*)$/.exec(message ?? '')
  if (!m) return message ?? ''
  const actor = ACTOR_LABEL[m[1]]
  const name = (code: string) => STATUS_LABEL[code as CallStatus] ?? code
  const move = /^([A-Z_]+) -> ([A-Z_]+)(?:: ([\s\S]*))?$/.exec(m[2])
  if (move) {
    // 로봇 큐의 내부 번호는 화면에 보여주지 않는다
    const reason = stageText((move[3] ?? '').replace(/^queue_item_id=\d+$/, ''))
    return `${actor}: ${name(move[1])} → ${name(move[2])}${reason ? ` (${reason})` : ''}`
  }
  if (!m[2]) return actor
  return `${actor}: ${m[2] === 'registered' ? '등록' : stageText(m[2])}`
}
