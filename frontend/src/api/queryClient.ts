import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './client'

/** 4xx는 다시 시도해도 같은 결과라 바로 보여주고, 5xx·연결 실패만 한 번 더 시도한다 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 1
}

export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: shouldRetry } } })
}
