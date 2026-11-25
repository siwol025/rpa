import { formatDateTime, formatSeconds, fromInputValue, toInputValue } from './format'

describe('formatDateTime', () => {
  it('없거나 잘못된 값이면 -', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('abc')).toBe('-')
  })
  it('한국 시간으로 보여준다', () => {
    expect(formatDateTime('2026-11-20T10:30:00+09:00')).toBe('11/20 10:30')
    expect(formatDateTime('2026-11-20T15:30:00Z')).toBe('11/21 00:30')
  })
})

describe('입력칸 변환', () => {
  it('API 값과 입력칸 값을 오간다', () => {
    expect(toInputValue('2026-11-20T01:30:00Z')).toBe('2026-11-20T10:30')
    expect(fromInputValue('2026-11-20T10:30')).toBe('2026-11-20T10:30:00+09:00')
  })
  it('빈 값', () => {
    expect(toInputValue(null)).toBe('')
    expect(fromInputValue('')).toBeNull()
  })
})

describe('formatSeconds', () => {
  it('분:초, 소수는 버린다', () => {
    expect(formatSeconds(389)).toBe('6:29')
    expect(formatSeconds(65.9)).toBe('1:05')
  })
  it('0초와 없음을 구분한다', () => {
    expect(formatSeconds(0)).toBe('0:00')
    expect(formatSeconds(null)).toBe('-')
  })
})
