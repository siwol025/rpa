import { fillBuckets, periodLabel } from './trend'

const periods = (items: { period: string }[]) => items.map((b) => b.period)

describe('fillBuckets', () => {
  it('일: 빈 날을 0으로 채운다', () => {
    expect(
      fillBuckets([{ period: '2026-11-13', count: 2 }, { period: '2026-11-16', count: 1 }], 'day'),
    ).toEqual([
      { period: '2026-11-13', count: 2 },
      { period: '2026-11-14', count: 0 },
      { period: '2026-11-15', count: 0 },
      { period: '2026-11-16', count: 1 },
    ])
  })
  it('주: 7일 간격', () => {
    const r = fillBuckets([{ period: '2026-11-09', count: 1 }, { period: '2026-11-23', count: 3 }], 'week')
    expect(periods(r)).toEqual(['2026-11-09', '2026-11-16', '2026-11-23'])
  })
  it('월: 해를 넘긴다', () => {
    const r = fillBuckets([{ period: '2026-11-01', count: 1 }, { period: '2027-01-01', count: 3 }], 'month')
    expect(periods(r)).toEqual(['2026-11-01', '2026-12-01', '2027-01-01'])
  })
  it('시각이 붙은 값도 날짜만 쓴다', () => {
    const r = fillBuckets([{ period: '2026-11-01T00:00:00+09:00', count: 1 }, { period: '2026-12-01T00:00:00+09:00', count: 2 }], 'month')
    expect(r).toEqual([{ period: '2026-11-01', count: 1 }, { period: '2026-12-01', count: 2 }])
  })
  it('예상과 다른 형식이면 채우지 않고 받은 그대로 둔다', () => {
    expect(fillBuckets([{ period: '2026-W46', count: 1 }], 'week')).toEqual([{ period: '2026-W46', count: 1 }])
    expect(periodLabel('2026-W46', 'week')).toBe('2026-W46')
  })
  it('비어 있으면 그대로', () => {
    expect(fillBuckets([], 'day')).toEqual([])
  })
})

describe('periodLabel', () => {
  it('단위별 표시', () => {
    expect(periodLabel('2026-11-09', 'day')).toBe('11/9')
    expect(periodLabel('2026-11-09', 'week')).toBe('11/9 시작 주')
    expect(periodLabel('2026-11-01', 'month')).toBe('2026년 11월')
  })
})
