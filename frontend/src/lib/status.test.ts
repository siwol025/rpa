import { actionLabel, canRetry, categoryColorVar, STATUS_LABEL, statusTone } from './status'

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
  it('띄어쓰기가 있는 유형도 색을 찾는다', () => {
    expect(categoryColorVar('질의')).toBe('var(--s1)')
    expect(categoryColorVar('교육 내용')).toBe('var(--s4)')
    expect(categoryColorVar('기타 문의')).toBe('var(--s5)')
  })
  it('모르는 유형이면 회색', () => {
    expect(categoryColorVar('새 유형')).toBe('var(--line-strong)')
  })
  it('조치 상태를 우리말로 바꾸고, 없으면 -', () => {
    expect(actionLabel('OPEN')).toBe('미조치')
    expect(actionLabel('DONE')).toBe('조치 완료')
    expect(actionLabel(null)).toBe('-')
  })
})
