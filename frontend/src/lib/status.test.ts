import { actionLabel, canRetry, categoryColorVar, categoryLabel, logMessage, STATUS_LABEL, statusTone } from './status'

describe('처리 상태', () => {
  it('백엔드 상태 7개를 각각 표시한다', () => {
    expect(STATUS_LABEL).toEqual({
      REGISTERED: '등록됨',
      QUEUED: '처리 대기',
      STT_DONE: '전사 완료',
      STORED: '저장 완료',
      NEEDS_REVIEW: '검토 필요',
      FAILED: '실패',
      RETRY_REQUESTED: '재처리 요청됨',
    })
  })
  it('색조를 나눈다', () => {
    expect(statusTone('QUEUED')).toBe('running')
    expect(statusTone('RETRY_REQUESTED')).toBe('running')
    expect(statusTone('STORED')).toBe('done')
    expect(statusTone('NEEDS_REVIEW')).toBe('review')
    expect(statusTone('FAILED')).toBe('failed')
  })
})

describe('재처리 가능 조건 (architecture §5)', () => {
  it.each(['FAILED', 'NEEDS_REVIEW', 'STORED'] as const)('%s는 언제나 가능', (s) => {
    expect(canRetry(s, false)).toBe(true)
  })
  it.each(['REGISTERED', 'QUEUED', 'STT_DONE'] as const)('%s는 정체일 때만 가능', (s) => {
    expect(canRetry(s, false)).toBe(false)
    expect(canRetry(s, true)).toBe(true)
  })
  it('RETRY_REQUESTED는 정체여도 불가', () => {
    expect(canRetry('RETRY_REQUESTED', true)).toBe(false)
  })
})

describe('유형과 조치 상태', () => {
  it('유형 코드의 색과 한글 이름', () => {
    expect(categoryColorVar('INQUIRY')).toBe('var(--s1)')
    expect(categoryColorVar('EDUCATION')).toBe('var(--s4)')
    expect(['INQUIRY', 'COMPLAINT', 'SUGGESTION', 'EDUCATION', 'ETC'].map(categoryLabel)).toEqual(['질의', '불만', '건의', '교육 내용', '기타 문의'])
    expect(categoryColorVar('ETC')).toBe('var(--s5)')
  })
  it('모르는 유형이면 회색과 코드 그대로', () => {
    expect(categoryColorVar('NEW')).toBe('var(--line-strong)')
    expect(categoryLabel('NEW')).toBe('NEW')
  })
  it('조치 상태를 우리말로 바꾸고, 없으면 -', () => {
    expect(actionLabel('OPEN')).toBe('미조치')
    expect(actionLabel('DONE')).toBe('조치 완료')
    expect(actionLabel(null)).toBe('-')
  })
})

describe('처리 이력 문구 (백엔드 state_machine, robot_service)', () => {
  it.each([
    ['[robot] registered', '로봇: 등록'],
    ['[robot] QUEUED -> STT_DONE', '로봇: 처리 대기 → 전사 완료'],
    ['[web] FAILED -> RETRY_REQUESTED', '웹: 실패 → 재처리 요청됨'],
    ['[robot] QUEUED -> FAILED: [STT] 응답 없음: 시간 초과', '로봇: 처리 대기 → 실패 (전사: 응답 없음: 시간 초과)'],
    ['[robot] REGISTERED -> FAILED: [INPUT] 파일 손상', '로봇: 등록됨 → 실패 (입력: 파일 손상)'],
    ['[robot] STT_DONE -> FAILED: [PII]', '로봇: 전사 완료 → 실패 (개인정보 가리기)'],
    ['[robot] STT_DONE -> FAILED: [VALIDATION] 형식 오류', '로봇: 전사 완료 → 실패 (결과 검증: 형식 오류)'],
    ['[robot] [GENAI] 응답 지연', '로봇: AI 분석: 응답 지연'],
    ['[robot] STT_DONE -> FAILED: [NEW] 사유', '로봇: 전사 완료 → 실패 ([NEW] 사유)'],
    ['[robot] REGISTERED -> QUEUED: queue_item_id=7', '로봇: 등록됨 → 처리 대기'],
    ['[robot] NEW_ONE -> QUEUED', '로봇: NEW_ONE → 처리 대기'],
    ['[robot] 엑셀 기입 실패', '로봇: 엑셀 기입 실패'],
    ['[robot]', '로봇'],
    ['[STT] 그대로', '[STT] 그대로'],
    ['음성이 너무 짧아요', '음성이 너무 짧아요'],
    [null, ''],
  ])('%s', (message, expected) => {
    expect(logMessage(message)).toBe(expected)
  })
})
