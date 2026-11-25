import { deleteCall, fetchCall, fetchCalls, retryCall, updateCall } from '../api/calls'
import { fetchBreakdown, fetchSummary, fetchTrend } from '../api/stats'
import type { CallListItem, CallListParams } from '../api/types'
import { MOCK_CALLS } from './data'

const list = (p: Partial<CallListParams> = {}) => fetchCalls({ page: 1, size: 100, ...p })

describe('mock: 목록', () => {
  it('최신순·오래된순 모두 일시 없는 건은 맨 뒤', async () => {
    const desc = (await list({ sort: '-call_datetime' })).items.map((c) => c.call_datetime)
    expect(desc.at(-1)).toBeNull()
    const dated = desc.slice(0, -1) as string[]
    expect([...dated].sort().reverse()).toEqual(dated)
    const asc = (await list({ sort: 'call_datetime' })).items.map((c) => c.call_datetime)
    expect(asc.at(-1)).toBeNull()
    expect(asc[0]).toBe('2026-11-10T09:12:00+09:00')
  })

  it('목록에는 전사가 없다', async () => {
    expect((await list()).items[0]).not.toHaveProperty('transcript')
  })

  it.each<[string, Partial<CallListParams>, (c: CallListItem) => boolean]>([
    ['유형', { category: 'EDUCATION' }, (c) => c.category === 'EDUCATION'],
    ['담당자', { agent: '김상담' }, (c) => c.agent_name === '김상담'],
    ['고객사', { client: 'B물류' }, (c) => c.client_company === 'B물류'],
    ['상태', { status: ['FAILED', 'QUEUED'] }, (c) => ['FAILED', 'QUEUED'].includes(c.status)],
    ['정체', { stale: true }, (c) => c.is_stale],
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

  it('항목에 등록 시각이 있다', async () => {
    const { items } = await list()
    expect(items.every((c) => !Number.isNaN(Date.parse(c.created_at)))).toBe(true)
    expect(await fetchCall(1)).toHaveProperty('created_at')
  })

  it('정렬을 보내지 않으면 등록순(최근 먼저)', async () => {
    const times = (await list()).items.map((c) => Date.parse(c.created_at))
    expect([...times].sort((a, b) => b - a)).toEqual(times)
  })

  it('키워드는 앞뒤 공백을 지우고 대소문자를 구분하지 않는다', async () => {
    expect((await list({ q: ' 분실 ' })).total).toBe(1)
    const upper = await list({ q: 'OTP' })
    expect(upper.total).toBeGreaterThan(0)
    expect((await list({ q: 'otp' })).total).toBe(upper.total)
  })

  it.each<[string, Partial<CallListParams>]>([
    ['시작일이 늦음', { from: '2026-11-20', to: '2026-11-10' }],
    ['범위 밖 날짜', { from: '1999-12-31' }],
    ['긴 키워드', { q: '가'.repeat(101) }],
    ['모르는 유형', { category: '질의' as never }],
    ['모르는 상태', { status: 'SUCCESS' as never }],
  ])('백엔드처럼 422: %s', async (_, params) => {
    await expect(list(params)).rejects.toMatchObject({ status: 422, code: 'VALIDATION_ERROR' })
  })

  it.each([
    ['빈 이름', { agent_name: ' ' }],
    ['긴 이름', { agent_name: '가'.repeat(51) }],
    ['빈 요약', { question_summary: ' ' }],
    ['긴 요약', { action_summary: '가'.repeat(2001) }],
    ['비울 수 없는 값', { category: null as never }],
    ['범위 밖 통화 일시', { call_datetime: '1999-12-31T23:59:00+09:00' }],
  ])('백엔드처럼 수정 422: %s', async (_, patch) => {
    await expect(updateCall(1, patch)).rejects.toMatchObject({ status: 422, code: 'VALIDATION_ERROR' })
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
  it('요약은 앞뒤 공백을 지우고 null로 비운다', async () => {
    const c = await updateCall(1, { question_summary: ' 문의 ', action_summary: null })
    expect(c.analysis).toMatchObject({ question_summary: '문의', action_summary: null })
  })
  it('분석 결과가 없으면 분석 수정은 409이고 함께 보낸 값도 바뀌지 않는다', async () => {
    const before = (await fetchCall(24)).agent_name
    await expect(updateCall(24, { category: 'ETC', agent_name: '새이름' })).rejects.toMatchObject({ status: 409, message: '분석 결과가 없는 상담입니다.' })
    expect((await fetchCall(24)).agent_name).toBe(before)
  })
  it('검토 완료는 이력을 남긴다', async () => {
    const c = await updateCall(7, { review_completed: true })
    expect(c.processing_log.at(-1)).toMatchObject({ step: 'STORE', status: 'SUCCESS', message: '[web] NEEDS_REVIEW -> STORED: 검토 완료' })
  })
  it('검토 완료는 NEEDS_REVIEW에서만', async () => {
    expect((await updateCall(7, { review_completed: true })).status).toBe('STORED')
    await expect(updateCall(7, { review_completed: true })).rejects.toMatchObject({ status: 409, code: 'INVALID_STATE_TRANSITION' })
  })
  it('재처리는 상태와 횟수를 바꾸고, 처리 중이면 409', async () => {
    expect(await retryCall(21)).toEqual({ call_id: 21, status: 'RETRY_REQUESTED', retry_count: 1 })
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
  it('요약: 총 건수와 유형별만 기간을 따르고 나머지는 전체 건수', async () => {
    const all = { action_open: 6, needs_review: 2, metadata_incomplete: 2, failed: 2, stale: 2 }
    expect(await fetchSummary({ from: '2026-11-10', to: '2026-11-24' })).toEqual({
      total: 26,
      by_category: { INQUIRY: 7, COMPLAINT: 5, SUGGESTION: 2, EDUCATION: 3, ETC: 2 },
      ...all,
    })
    expect(await fetchSummary({ from: '2020-01-01', to: '2020-01-02' })).toMatchObject({ total: 0, ...all })
  })
  it('추이와 분류', async () => {
    expect((await fetchTrend({ granularity: 'week' })).items).toEqual([
      { period: '2026-11-09', count: 8 },
      { period: '2026-11-16', count: 11 },
      { period: '2026-11-23', count: 7 },
    ])
    const { items } = await fetchBreakdown({ by: 'agent' })
    expect(items[0]).toMatchObject({ name: '김상담', count: 9 })
    expect(items.at(-1)).toMatchObject({ name: null, count: 2 })
    expect(items.reduce((n, i) => n + i.count, 0)).toBe(MOCK_CALLS.length)
    expect(items.reduce((n, i) => n + i.by_category.INQUIRY, 0)).toBe(7)
  })
  it('추이는 기간 안의 빈 구간도 0으로 준다', async () => {
    const { items } = await fetchTrend({ granularity: 'day', from: '2026-11-13', to: '2026-11-16' })
    expect(items.map((i) => i.period)).toEqual(['2026-11-13', '2026-11-14', '2026-11-15', '2026-11-16'])
    expect(items[1].count).toBe(0)
    expect((await fetchTrend({ granularity: 'day', from: '2020-01-01', to: '2020-01-05' })).items).toEqual([])
  })
  it('백엔드처럼 구간이 400개를 넘으면 422', async () => {
    await expect(fetchTrend({ granularity: 'day', from: '2025-01-01', to: '2026-02-05' })).rejects.toMatchObject({ status: 422, detail: { errors: [{ type: 'range_too_large' }] } })
    expect((await fetchTrend({ granularity: 'month', from: '2025-01-01', to: '2026-11-30' })).items).toHaveLength(23)
  })
})
