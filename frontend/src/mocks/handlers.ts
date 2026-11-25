import { delay, http, HttpResponse } from 'msw'
import { CATEGORIES, PAGE_MAX, PAGE_SIZE_MAX, Q_MAX_LENGTH, STATUSES, SUMMARY_MAX_LENGTH, type CallDetail, type CallListItem, type CallPatch, type RetryResult, type TrendItem } from '../api/types'
import { canRetry } from '../lib/status'
import { periodProblem } from '../lib/useUrlParams'
import { MOCK_CALLS } from './data'

const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const WAIT = import.meta.env.MODE === 'test' ? 0 : 200

let db: CallDetail[] = structuredClone(MOCK_CALLS)
export function resetDb() {
  db = structuredClone(MOCK_CALLS)
}

const error = (status: number, code: string, message: string) => HttpResponse.json({ code, message, detail: null }, { status })
const notFound = () => error(404, 'NOT_FOUND', '대상을 찾을 수 없습니다.')
const invalidRequest = () => error(422, 'VALIDATION_ERROR', '요청 형식이 올바르지 않습니다.')
const invalidState = (message = '현재 상태에서 허용되지 않는 요청입니다.') => error(409, 'INVALID_STATE_TRANSITION', message)
const find = (id: unknown) => db.find((c) => c.id === Number(id))
const now = () => new Date().toISOString()

function toItem(c: CallDetail): CallListItem {
  const { transcript: _t, analysis, processing_log: _l, ...base } = c
  return {
    ...base,
    category: analysis?.category ?? null,
    question_summary: analysis?.question_summary ?? null,
    action_status: analysis?.action_status ?? null,
  }
}

function inPeriod(c: CallDetail, sp: URLSearchParams): boolean {
  const from = sp.get('from')
  const to = sp.get('to')
  if (!from && !to) return true
  const day = c.call_datetime?.slice(0, 10)
  return !!day && (!from || day >= from) && (!to || day <= to)
}

function positive(value: string | null, fallback: number): number {
  const n = Math.floor(Number(value))
  return n >= 1 ? n : fallback
}

function bucket(iso: string, g: string | null): string {
  const day = iso.slice(0, 10)
  if (g === 'month') return `${day.slice(0, 7)}-01`
  if (g !== 'week') return day
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7))
  return d.toISOString().slice(0, 10)
}

const TREND_MAX = 400

function nextBucket(period: string, g: string | null): string {
  const d = new Date(`${period}T00:00:00Z`)
  if (g === 'month') d.setUTCMonth(d.getUTCMonth() + 1)
  else d.setUTCDate(d.getUTCDate() + (g === 'week' ? 7 : 1))
  return d.toISOString().slice(0, 10)
}

const rangeTooLarge = () =>
  HttpResponse.json(
    {
      code: 'VALIDATION_ERROR',
      message: '요청 형식이 올바르지 않습니다.',
      detail: { errors: [{ loc: ['query', 'from'], msg: `기간이 너무 깁니다. 구간은 최대 ${TREND_MAX}개입니다`, type: 'range_too_large' }] },
    },
    { status: 422 },
  )

/** 소리 없는 2초짜리 wav (재생 화면 확인용) */
function silentWav(): ArrayBuffer {
  const rate = 8000
  const size = rate * 2
  const buf = new ArrayBuffer(44 + size)
  const v = new DataView(buf)
  const text = (o: number, s: string) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)))
  text(0, 'RIFF')
  v.setUint32(4, 36 + size, true)
  text(8, 'WAVEfmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true)
  v.setUint16(22, 1, true)
  v.setUint32(24, rate, true)
  v.setUint32(28, rate, true)
  v.setUint16(32, 1, true)
  v.setUint16(34, 8, true)
  text(36, 'data')
  v.setUint32(40, size, true)
  new Uint8Array(buf, 44).fill(128)
  return buf
}

export const handlers = [
  http.get(`*${BASE}/calls`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const q = (sp.get('q') ?? '').trim().toLowerCase()
    const is = (key: string, value: string | null | undefined) => !sp.get(key) || sp.get(key) === value
    const statuses = sp.getAll('status')
    const badCode = (key: string, allowed: readonly string[]) => sp.getAll(key).some((v) => !allowed.includes(v))
    if (
      periodProblem({ from: sp.get('from') ?? undefined, to: sp.get('to') ?? undefined }) ||
      [...(sp.get('q') ?? '')].length > Q_MAX_LENGTH ||
      badCode('category', CATEGORIES) ||
      badCode('status', STATUSES)
    ) {
      return invalidRequest()
    }
    const sort = sp.get('sort') ?? '-created_at'
    const dir = sort.startsWith('-') ? -1 : 1
    const field = sort.replace('-', '')
    if (!['call_datetime', 'created_at', 'status_changed_at'].includes(field)) return invalidRequest()
    const key = (c: CallDetail) =>
      field === 'call_datetime' ? c.call_datetime : field === 'status_changed_at' ? c.status_changed_at : c.created_at
    const rows = db
      .filter(
        (c) =>
          inPeriod(c, sp) &&
          is('category', c.analysis?.category) &&
          is('agent', c.agent_name) &&
          is('client', c.client_company) &&
          (statuses.length === 0 || statuses.includes(c.status)) &&
          is('stale', String(c.is_stale)) &&
          is('metadata_incomplete', String(c.metadata_incomplete)) &&
          (!q ||
            [c.analysis?.question_summary, c.analysis?.action_summary, ...(c.transcript?.segments.map((s) => s.text) ?? [])]
              .join(' ')
              .toLowerCase()
              .includes(q)),
      )
      .sort((a, b) => {
        const [x, y] = [key(a), key(b)]
        if (!x || !y) return Number(!x) - Number(!y)
        return dir * (Date.parse(x) - Date.parse(y) || a.id - b.id)
      })
    const page = positive(sp.get('page'), 1)
    const size = positive(sp.get('size'), 20)
    if (page > PAGE_MAX || size > PAGE_SIZE_MAX) return invalidRequest()
    return HttpResponse.json({ items: rows.slice((page - 1) * size, page * size).map(toItem), page, size, total: rows.length })
  }),

  http.get(`*${BASE}/calls/:id`, async ({ params }) => {
    await delay(WAIT)
    const c = find(params.id)
    return c ? HttpResponse.json(c) : notFound()
  }),

  http.patch(`*${BASE}/calls/:id`, async ({ params, request }) => {
    await delay(WAIT)
    const c = find(params.id)
    if (!c) return notFound()
    const p = (await request.json()) as CallPatch
    const badText = (v: string | null | undefined, max: number) => typeof v === 'string' && (!v.trim() || [...v.trim()].length > max)
    const day = p.call_datetime?.slice(0, 10)
    if (
      badText(p.agent_name, 50) ||
      badText(p.client_company, 100) ||
      badText(p.editor, 50) ||
      badText(p.question_summary, SUMMARY_MAX_LENGTH) ||
      badText(p.action_summary, SUMMARY_MAX_LENGTH) ||
      [p.category, p.action_status, p.review_completed].some((v) => v === null) ||
      (day && periodProblem({ from: day }))
    ) {
      return invalidRequest()
    }
    // 409는 어떤 값도 바꾸기 전에 낸다
    const editsAnalysis = [p.category, p.question_summary, p.action_summary, p.action_status].some((v) => v !== undefined)
    if (editsAnalysis && !c.analysis) return invalidState('분석 결과가 없는 상담입니다.')
    if (p.review_completed && c.status !== 'NEEDS_REVIEW') return invalidState()
    if (c.analysis) {
      if (p.category !== undefined) c.analysis.category = p.category
      if (p.question_summary !== undefined) c.analysis.question_summary = p.question_summary?.trim() ?? null
      if (p.action_summary !== undefined) c.analysis.action_summary = p.action_summary?.trim() ?? null
      if (p.action_status !== undefined) c.analysis.action_status = p.action_status
    }
    if (p.agent_name !== undefined) c.agent_name = p.agent_name?.trim() ?? null
    if (p.client_company !== undefined) c.client_company = p.client_company?.trim() ?? null
    if (p.call_datetime !== undefined) c.call_datetime = p.call_datetime
    c.metadata_incomplete = !c.agent_name || !c.call_datetime
    if (p.review_completed) {
      c.status = 'STORED'
      c.status_changed_at = now()
      if (c.analysis) c.analysis.needs_review = false
      c.processing_log.push({ step: 'STORE', status: 'SUCCESS', message: '[web] NEEDS_REVIEW -> STORED: 검토 완료', created_at: now() })
    }
    return HttpResponse.json(c)
  }),

  http.delete(`*${BASE}/calls/:id`, async ({ params }) => {
    await delay(WAIT)
    if (!find(params.id)) return notFound()
    db = db.filter((c) => c.id !== Number(params.id))
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`*${BASE}/calls/:id/retry`, async ({ params }) => {
    await delay(WAIT)
    const c = find(params.id)
    if (!c) return notFound()
    if (!canRetry(c.status, c.is_stale)) return invalidState()
    c.status = 'RETRY_REQUESTED'
    c.status_changed_at = now()
    c.is_stale = false
    c.retry_count += 1
    c.processing_log.push({ step: 'RETRY', status: 'RETRY', message: null, created_at: now() })
    const result: RetryResult = { call_id: c.id, status: c.status, retry_count: c.retry_count }
    return HttpResponse.json(result, { status: 202 })
  }),

  http.get(`*${BASE}/calls/:id/audio`, ({ params }) =>
    find(params.id) ? new HttpResponse(silentWav(), { headers: { 'Content-Type': 'audio/wav' } }) : notFound(),
  ),

  http.get(`*${BASE}/stats/summary`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const rows = db.filter((c) => inPeriod(c, sp))
    // 총 건수와 유형별만 기간을 따른다 (규약 §4.3)
    const n = (f: (c: CallDetail) => boolean) => db.filter(f).length
    return HttpResponse.json({
      total: rows.length,
      by_category: Object.fromEntries(CATEGORIES.map((k) => [k, rows.filter((c) => c.analysis?.category === k).length])),
      action_open: n((c) => c.analysis?.action_status === 'OPEN'),
      needs_review: n((c) => c.status === 'NEEDS_REVIEW'),
      metadata_incomplete: n((c) => c.metadata_incomplete),
      failed: n((c) => c.status === 'FAILED'),
      stale: n((c) => c.is_stale),
    })
  }),

  http.get(`*${BASE}/stats/trend`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const g = sp.get('granularity')
    const counts = new Map<string, number>()
    for (const c of db.filter((x) => inPeriod(x, sp))) {
      if (!c.call_datetime) continue
      const b = bucket(c.call_datetime, g)
      counts.set(b, (counts.get(b) ?? 0) + 1)
    }
    const [from, to] = [sp.get('from'), sp.get('to')]
    const found = [...counts.keys()].sort()
    const first = from ? bucket(from, g) : found[0]
    const last = to ? bucket(to, g) : found.at(-1)
    const items: TrendItem[] = []
    for (let p = first; p && last && p <= last; p = nextBucket(p, g)) {
      if (items.length === TREND_MAX) return rangeTooLarge()
      items.push({ period: p, count: counts.get(p) ?? 0 })
    }
    return HttpResponse.json({ granularity: g ?? 'day', items: found.length ? items : [] })
  }),

  http.get(`*${BASE}/stats/breakdown`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const key = sp.get('by') === 'client' ? 'client_company' : 'agent_name'
    const groups = new Map<string | null, CallDetail[]>()
    for (const c of db.filter((x) => inPeriod(x, sp))) {
      const name = c[key]?.trim() ? c[key] : null
      groups.set(name, [...(groups.get(name) ?? []), c])
    }
    const items = [...groups].map(([name, calls]) => ({
      name,
      count: calls.length,
      by_category: Object.fromEntries(CATEGORIES.map((k) => [k, calls.filter((c) => c.analysis?.category === k).length])),
    }))
    items.sort((a, b) => Number(a.name === null) - Number(b.name === null) || b.count - a.count || (a.name ?? '').localeCompare(b.name ?? ''))
    return HttpResponse.json({ by: sp.get('by'), items })
  }),

  http.get(`*${BASE}/reports/excel`, async () => {
    await delay(WAIT)
    // 열리지 않는 가짜 파일을 주는 대신 알린다
    return error(501, 'MOCK_ONLY', '예시 데이터 모드에서는 엑셀 파일을 만들지 않아요.')
  }),

  http.post(`*${BASE}/uploads`, async ({ request }) => {
    await delay(WAIT)
    const files = (await request.formData()).getAll('files').filter((f) => f instanceof File)
    return HttpResponse.json({ items: files.map((f) => ({ name: f.name.replace(/[^.]+$/, (ext) => ext.toLowerCase()) })) }, { status: 202 })
  }),
]
