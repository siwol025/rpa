const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const DEFAULT_TIMEOUT_MS = 15_000

type Params = Record<string, string | number | boolean | undefined>
interface Options {
  timeoutMs?: number
}

export class ApiError extends Error {
  status: number
  code: string
  detail: unknown
  requestId: string | null

  constructor(status: number, code: string, message: string, requestId: string | null = null, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
    this.requestId = requestId
  }
}

/** 빈 값과 false는 보내지 않는다 (켜진 필터만 전달) */
export function toQueryString(params: Params): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === '' || v === false) continue
    sp.append(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

function fallbackMessage(status: number): string {
  if (status === 413) return '파일이 너무 커요.'
  if (status >= 500) return '서버에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.'
  return '요청을 처리하지 못했어요.'
}

/** 에러 본문은 {code, message, detail}. message는 화면에 그대로 보여줄 수 있는 한국어 (백엔드 core/errors.py) */
async function toApiError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get('X-Request-Id')
  let body: { code?: string; message?: string; detail?: unknown } | null = null
  try {
    body = await res.json()
  } catch {
    // 본문이 JSON이 아니면 상태 코드만으로 처리
  }
  if (requestId) console.warn(`[api] ${res.status} ${new URL(res.url || 'http://localhost').pathname} request-id=${requestId}`)
  return new ApiError(res.status, body?.code ?? `HTTP_${res.status}`, body?.message || fallbackMessage(res.status), requestId, body?.detail ?? null)
}

async function request(path: string, init: RequestInit, opts: Options): Promise<Response> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  let res: Response
  try {
    res = await fetch(url, { ...init, signal: AbortSignal.timeout(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS) })
  } catch (e) {
    // 실행 환경마다 DOMException 클래스가 달라서 instanceof 대신 이름으로 확인
    if ((e as { name?: string } | null)?.name === 'TimeoutError') {
      throw new ApiError(0, 'TIMEOUT', '서버 응답이 너무 늦어요. 잠시 후 다시 시도해 주세요.')
    }
    throw new ApiError(0, 'NETWORK', '서버에 연결할 수 없어요.')
  }
  if (!res.ok) throw await toApiError(res)
  return res
}

async function readJson<T>(res: Response): Promise<T> {
  try {
    return (await res.json()) as T
  } catch {
    // 예: 백엔드 대신 개발 서버가 index.html을 돌려준 경우
    throw new ApiError(res.status, 'BAD_RESPONSE', '서버 응답을 읽지 못했어요.')
  }
}

export async function apiGet<T>(path: string, params: Params = {}, opts: Options = {}): Promise<T> {
  return readJson<T>(await request(`${path}${toQueryString(params)}`, {}, opts))
}

/** 본문이 없는 응답(204, 빈 202)은 undefined */
export async function apiSend<T = void>(method: 'POST' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await request(path, init, {})
  const text = await res.text()
  if (!text) return undefined as T
  return readJson<T>(new Response(text, { status: res.status }))
}

export async function apiUpload(path: string, form: FormData, opts: Options): Promise<void> {
  await request(path, { method: 'POST', body: form }, opts)
}

export async function apiBlob(path: string, params: Params = {}, opts: Options = {}): Promise<Blob> {
  return (await request(`${path}${toQueryString(params)}`, {}, opts)).blob()
}

export function apiUrl(path: string): string {
  return `${BASE}${path}`
}
