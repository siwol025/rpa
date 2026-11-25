import { useCallback, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { DATE_MAX, DATE_MIN, type Period } from '../api/types'

const DATE = /^\d{4}-\d{2}-\d{2}$/

/** 주소의 값이 날짜 형식일 때만 쓴다 */
export function dateParam(sp: URLSearchParams, key: string): string | undefined {
  const v = sp.get(key)
  return v && DATE.test(v) ? v : undefined
}

/** 서버가 받지 않는 기간이면 안내 문구 (규약 §4.3) */
export function periodProblem({ from, to }: Period): string | null {
  if ([from, to].some((d) => d && (d < DATE_MIN || d > DATE_MAX))) return '날짜는 2000년부터 2100년까지 고를 수 있어요'
  if (from && to && from > to) return '시작일이 종료일보다 늦어요'
  return null
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
