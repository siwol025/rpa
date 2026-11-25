import { actionLabel, canRetry, categoryColorVar, categoryLabel, STATUS_LABEL, statusTone } from './status'

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
  it('정체 여부를 모르면 정체가 아닌 것으로 본다', () => {
    expect(canRetry('QUEUED', undefined)).toBe(false)
    expect(canRetry('FAILED', undefined)).toBe(true)
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
