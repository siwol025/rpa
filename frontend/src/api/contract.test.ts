import { delay, http, HttpResponse } from 'msw'
import { server } from '../mocks/server'
import { ApiError, apiBlob, apiGet, apiSend, toQueryString } from './client'
import { shouldRetry } from './queryClient'

const url = '*/api/test'

async function catchError(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p
  } catch (e) {
    return e as ApiError
  }
  throw new Error('에러가 나지 않았음')
}

const fail = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  server.use(http.all(url, () => HttpResponse.json(body as never, { status, headers })))

describe('toQueryString', () => {
  it('빈 값과 false는 빼고 특수문자를 인코딩한다', () => {
    expect(toQueryString({ q: '카드 100%&해지', page: 1, stale: false, inc: true, type: undefined, agent: '' })).toBe(
      '?q=%EC%B9%B4%EB%93%9C+100%25%26%ED%95%B4%EC%A7%80&page=1&inc=true',
    )
  })
  it('여러 값은 같은 이름을 반복한다', () => {
    expect(toQueryString({ status: ['FAILED', 'QUEUED'], size: 5 })).toBe('?status=FAILED&status=QUEUED&size=5')
  })
  it('값이 없으면 빈 문자열', () => {
    expect(toQueryString({})).toBe('')
  })
})

describe('에러 응답 {code, message, detail}', () => {
  it('서버 메시지를 그대로 쓰고 detail을 담는다', async () => {
    const body = { code: 'INVALID_STATE_TRANSITION', message: '현재 상태에서 허용되지 않는 요청입니다.', detail: { status: 'QUEUED' } }
    fail(409, body)
    const err = await catchError(apiSend('POST', '/test'))
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 409, ...body })
  })
  it('500도 서버 메시지를 쓴다', async () => {
    fail(500, { code: 'INTERNAL_ERROR', message: '서버 내부 오류가 발생했습니다.', detail: null })
    expect((await catchError(apiGet('/test'))).message).toBe('서버 내부 오류가 발생했습니다.')
  })
  it('본문이 JSON이 아니면 상태에 맞는 문구', async () => {
    server.use(http.get(url, () => new HttpResponse('Bad Gateway', { status: 502 })))
    const bad = await catchError(apiGet('/test'))
    expect(bad).toMatchObject({ code: 'HTTP_502', message: '서버에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.' })
    server.use(http.get(url, () => new HttpResponse(null, { status: 413 })))
    expect((await catchError(apiGet('/test'))).message).toBe('파일이 너무 커요.')
  })
  it('JSON이지만 형식이 다르면 기본 문구', async () => {
    fail(400, null)
    expect((await catchError(apiGet('/test'))).message).toBe('요청을 처리하지 못했어요.')
  })
  it('X-Request-Id를 담는다', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    fail(400, { code: 'BAD_REQUEST', message: 'm', detail: null }, { 'X-Request-Id': 'abc' })
    expect((await catchError(apiGet('/test'))).requestId).toBe('abc')
    warn.mockRestore()
  })
  it('연결 실패', async () => {
    server.use(http.get(url, () => HttpResponse.error()))
    expect(await catchError(apiGet('/test'))).toMatchObject({ status: 0, code: 'NETWORK', message: '서버에 연결할 수 없어요.' })
  })
  it('시간 초과', async () => {
    server.use(
      http.get(url, async () => {
        await delay('infinite')
        return HttpResponse.json({})
      }),
    )
    expect(await catchError(apiGet('/test', {}, { timeoutMs: 50 }))).toMatchObject({ code: 'TIMEOUT' })
  })
  it('성공 응답이 JSON이 아니면', async () => {
    server.use(http.get(url, () => new HttpResponse('<!doctype html>', { headers: { 'Content-Type': 'text/html' } })))
    expect(await catchError(apiGet('/test'))).toMatchObject({ code: 'BAD_RESPONSE', message: '서버 응답을 읽지 못했어요.' })
  })
})

describe('apiSend / apiBlob', () => {
  it('JSON 본문을 보낸다', async () => {
    let got: unknown
    server.use(
      http.patch(url, async ({ request }) => {
        got = await request.json()
        return HttpResponse.json({ ok: 1 })
      }),
    )
    await expect(apiSend('PATCH', '/test', { a: 1 })).resolves.toEqual({ ok: 1 })
    expect(got).toEqual({ a: 1 })
  })
  it('본문 없는 204를 받는다', async () => {
    server.use(http.delete(url, () => new HttpResponse(null, { status: 204 })))
    await expect(apiSend('DELETE', '/test')).resolves.toBeUndefined()
  })
  it('파일을 받는다', async () => {
    server.use(http.get(url, () => new HttpResponse('xlsx', { headers: { 'Content-Type': 'application/octet-stream' } })))
    expect((await apiBlob('/test')).size).toBe(4)
  })
})

describe('재시도 규칙', () => {
  it('4xx는 안 하고 5xx·연결 실패만 한 번', () => {
    expect(shouldRetry(0, new ApiError(404, 'NOT_FOUND', 'x'))).toBe(false)
    expect(shouldRetry(0, new ApiError(500, 'X', 'x'))).toBe(true)
    expect(shouldRetry(0, new ApiError(0, 'NETWORK', 'x'))).toBe(true)
    expect(shouldRetry(1, new ApiError(500, 'X', 'x'))).toBe(false)
  })
})
