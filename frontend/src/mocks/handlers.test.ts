import { deleteCall, fetchCall, fetchCalls, retryCall, updateCall } from '../api/calls'
import { fetchBreakdown, fetchSummary, fetchTrend } from '../api/stats'
import type { CallListItem, CallListParams } from '../api/types'
import { MOCK_CALLS } from './data'

const list = (p: Partial<CallListParams> = {}) => fetchCalls({ page: 1, size: 100, ...p })

describe('mock: 목록', () => {
  it('최신순·오래된순 모두 일시 없는 건은 맨 뒤', async () => {
    const desc = (await list()).items.map((c) => c.call_datetime)
    expect(desc.at(-1)).toBeNull()
    const dated = desc.slice(0, -1) as string[]
    expect([...dated].sort().reverse()).toEqual(dated)
    const asc = (await list({ sort: 'call_datetime:asc' })).items.map((c) => c.call_datetime)
    expect(asc.at(-1)).toBeNull()
    expect(asc[0]).toBe('2026-11-10T09:12:00+09:00')
  })

  it('목록에는 전사가 없다', async () => {
    expect((await list()).items[0]).not.toHaveProperty('transcript')
  })

  it.each<[string, Partial<CallListParams>, (c: CallListItem) => boolean]>([
    ['유형', { category: '교육 내용' }, (c) => c.category === '교육 내용'],
    ['담당자', { agent: '김상담' }, (c) => c.agent_name === '김상담'],
    ['고객사', { client: 'B물류' }, (c) => c.client_company === 'B물류'],
    ['상태', { status: 'FAILED' }, (c) => c.status === 'FAILED'],
    ['정체', { stale: true }, (c) => c.stale],
    ['메타데이터', { metadata_incomplete: true }, (c) => c.metadata_incomplete],
    ['기간', { from: '2026-11-16', to: '2026-11-17' }, (c) => /^2026-11-1[67]/.test(c.call_datetime ?? '')],
  ])('%s 필터', async (_, params, ok) => {
    const { items } = await list(params)
    expect(items.length).toBeGreaterThan(0)
    expect(items.every(ok)).toBe(true)
  })

  it('키워드는 요약·조치·전사에서 찾는다', async () => {
    expect((await list({ q: '분실' })).total).toBe(1)
  })

  it('범위를 넘는 페이지는 빈 목록', async () => {
    expect(await fetchCalls({ page: 99, size: 20 })).toMatchObject({ items: [], total: MOCK_CALLS.length })
  })
})

describe('mock: 상세와 변경', () => {
  it('없는 상담은 404와 서버 메시지', async () => {
    await expect(fetchCall(99999)).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND', message: '대상을 찾을 수 없습니다.' })
  })
  it('메타데이터를 채우면 확인 필요가 풀린다', async () => {
    const c = await updateCall(20, { agent_name: '김상담', call_datetime: '2026-11-23T11:12:00+09:00', editor: '홍' })
    expect(c.metadata_incomplete).toBe(false)
  })
  it('검토 완료는 NEEDS_REVIEW에서만', async () => {
    expect((await updateCall(7, { review_completed: true })).status).toBe('STORED')
    await expect(updateCall(7, { review_completed: true })).rejects.toMatchObject({ status: 409, code: 'INVALID_STATE_TRANSITION' })
  })
  it('재처리는 상태와 횟수를 바꾸고, 처리 중이면 409', async () => {
    await retryCall(21)
    expect(await fetchCall(21)).toMatchObject({ status: 'RETRY_REQUESTED', retry_count: 1 })
    await expect(retryCall(24)).rejects.toMatchObject({ status: 409 })
  })
  it('삭제하면 조회되지 않는다', async () => {
    await deleteCall(1)
    await expect(fetchCall(1)).rejects.toMatchObject({ status: 404 })
  })
  it('테스트마다 데이터가 처음으로 돌아온다', async () => {
    expect((await list()).total).toBe(MOCK_CALLS.length)
    expect((await fetchCall(7)).status).toBe('NEEDS_REVIEW')
  })
})

describe('mock: 통계', () => {
  it('요약', async () => {
    expect(await fetchSummary({ from: '2026-11-10', to: '2026-11-24' })).toEqual({
      total: 26,
      by_category: { 질의: 7, 불만: 5, 건의: 2, '교육 내용': 3, '기타 문의': 2 },
      action_open: 5,
      needs_review: 2,
      metadata_incomplete: 1,
      failed: 2,
      stale: 2,
    })
  })
  it('추이와 분류', async () => {
    expect((await fetchTrend({ granularity: 'week' })).items).toEqual([
      { period: '2026-11-09', count: 8 },
      { period: '2026-11-16', count: 11 },
      { period: '2026-11-23', count: 7 },
    ])
    expect((await fetchBreakdown({ by: 'agent' })).items[0]).toEqual({ name: '김상담', count: 9 })
  })
})
