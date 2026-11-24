import { useCallback, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

const DATE = /^\d{4}-\d{2}-\d{2}$/

/** 주소의 값이 날짜 형식일 때만 쓴다 */
export function dateParam(sp: URLSearchParams, key: string): string | undefined {
  const v = sp.get(key)
  return v && DATE.test(v) ? v : undefined
}

/** 주소의 값이 허용된 값일 때만 쓴다 */
export function oneOf<T extends string>(sp: URLSearchParams, key: string, allowed: readonly T[]): T | undefined {
  return allowed.find((a) => a === sp.get(key))
}

/**
 * 필터 값을 주소에 둔다. set(key, '')이면 지운다.
 * 타이머처럼 나중에 불려도 그 시점의 주소를 기준으로 바꾼다 (그사이 고른 필터를 덮어쓰지 않도록).
 */
export function useUrlParams() {
  const [sp, setSp] = useSearchParams()
  const latest = useRef({ sp, setSp })
  useEffect(() => {
    latest.current = { sp, setSp }
  })
  const set = useCallback((key: string, value: string, opts: { keepPage?: boolean } = {}) => {
    const next = new URLSearchParams(latest.current.sp)
    if (value) next.set(key, value)
    else next.delete(key)
    if (!opts.keepPage) next.delete('page')
    latest.current.setSp(next)
  }, [])
  return { sp, set }
}
