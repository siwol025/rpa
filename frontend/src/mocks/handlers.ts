import { delay, http, HttpResponse } from 'msw'
import { CATEGORIES, type CallDetail, type CallListItem, type CallPatch } from '../api/types'
import { canRetry } from '../lib/status'
import { MOCK_CALLS } from './data'

const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const WAIT = import.meta.env.MODE === 'test' ? 0 : 200

let db: CallDetail[] = structuredClone(MOCK_CALLS)
export function resetDb() {
  db = structuredClone(MOCK_CALLS)
}

const error = (status: number, code: string, message: string) => HttpResponse.json({ code, message, detail: null }, { status })
const notFound = () => error(404, 'NOT_FOUND', '대상을 찾을 수 없습니다.')
const invalidState = () => error(409, 'INVALID_STATE_TRANSITION', '현재 상태에서 허용되지 않는 요청입니다.')
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

function countBy(values: string[]): [string, number][] {
  const m = new Map<string, number>()
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1)
  return [...m]
}

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
    const q = sp.get('q')
    const is = (key: string, value: string | null | undefined) => !sp.get(key) || sp.get(key) === value
    const dir = sp.get('sort') === 'call_datetime:asc' ? 1 : -1
    const rows = db
      .filter(
        (c) =>
          inPeriod(c, sp) &&
          is('category', c.analysis?.category) &&
          is('agent', c.agent_name) &&
          is('client', c.client_company) &&
          is('status', c.status) &&
          is('stale', String(c.stale)) &&
          is('metadata_incomplete', String(c.metadata_incomplete)) &&
          (!q ||
            [c.analysis?.question_summary, c.analysis?.action_summary, ...(c.transcript?.segments.map((s) => s.text) ?? [])]
              .join(' ')
              .includes(q)),
      )
      .sort((a, b) => {
        if (!a.call_datetime || !b.call_datetime) return Number(!a.call_datetime) - Number(!b.call_datetime)
        return dir * a.call_datetime.localeCompare(b.call_datetime)
      })
    const page = positive(sp.get('page'), 1)
    const size = positive(sp.get('size'), 20)
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
    if (p.review_completed && c.status !== 'NEEDS_REVIEW') return invalidState()
    if (c.analysis) {
      if (p.category !== undefined) c.analysis.category = p.category
      if (p.question_summary !== undefined) c.analysis.question_summary = p.question_summary
      if (p.action_summary !== undefined) c.analysis.action_summary = p.action_summary
      if (p.action_status !== undefined) c.analysis.action_status = p.action_status
    }
    if (p.agent_name !== undefined) c.agent_name = p.agent_name
    if (p.client_company !== undefined) c.client_company = p.client_company
    if (p.call_datetime !== undefined) c.call_datetime = p.call_datetime
    c.metadata_incomplete = !c.agent_name || !c.call_datetime
    if (p.review_completed) {
      c.status = 'STORED'
      c.status_changed_at = now()
      if (c.analysis) c.analysis.needs_review = false
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
    if (!canRetry(c.status, c.stale)) return invalidState()
    c.status = 'RETRY_REQUESTED'
    c.status_changed_at = now()
    c.stale = false
    c.retry_count += 1
    c.processing_log.push({ step: 'RETRY', status: 'RETRY', message: null, created_at: now() })
    return new HttpResponse(null, { status: 202 })
  }),

  http.get(`*${BASE}/calls/:id/audio`, ({ params }) =>
    find(params.id) ? new HttpResponse(silentWav(), { headers: { 'Content-Type': 'audio/wav' } }) : notFound(),
  ),

  http.get(`*${BASE}/stats/summary`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const rows = db.filter((c) => inPeriod(c, sp))
    const n = (f: (c: CallDetail) => boolean) => rows.filter(f).length
    return HttpResponse.json({
      total: rows.length,
      by_category: Object.fromEntries(CATEGORIES.map((k) => [k, n((c) => c.analysis?.category === k)])),
      action_open: n((c) => c.analysis?.action_status === 'OPEN'),
      needs_review: n((c) => c.status === 'NEEDS_REVIEW'),
      metadata_incomplete: n((c) => c.metadata_incomplete),
      failed: n((c) => c.status === 'FAILED'),
      stale: n((c) => c.stale),
    })
  }),

  http.get(`*${BASE}/stats/trend`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const g = sp.get('granularity')
    const rows = countBy(db.filter((c) => inPeriod(c, sp)).flatMap((c) => (c.call_datetime ? [bucket(c.call_datetime, g)] : [])))
    return HttpResponse.json({ items: rows.sort(([a], [b]) => a.localeCompare(b)).map(([period, count]) => ({ period, count })) })
  }),

  http.get(`*${BASE}/stats/breakdown`, async ({ request }) => {
    await delay(WAIT)
    const sp = new URL(request.url).searchParams
    const key = sp.get('by') === 'client' ? 'client_company' : 'agent_name'
    const rows = countBy(db.filter((c) => inPeriod(c, sp)).flatMap((c) => c[key] ?? []))
    return HttpResponse.json({
      items: rows.sort(([an, a], [bn, b]) => b - a || an.localeCompare(bn)).map(([name, count]) => ({ name, count })),
    })
  }),

  http.get(`*${BASE}/reports/excel`, async () => {
    await delay(WAIT)
    // 열리지 않는 가짜 파일을 주는 대신 알린다
    return error(501, 'MOCK_ONLY', '예시 데이터 모드에서는 엑셀 파일을 만들지 않아요.')
  }),

  http.post(`*${BASE}/uploads`, async () => {
    await delay(WAIT)
    return new HttpResponse(null, { status: 202 })
  }),
]
