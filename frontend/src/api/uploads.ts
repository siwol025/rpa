import { ApiError, apiUpload, hasValidationError } from './client'
import type { UploadResult } from './types'

const UPLOAD_TIMEOUT_MS = 5 * 60_000

/**
 * 파일 하나를 올리고 서버가 저장한 이름을 돌려준다. 서버의 크기 제한은 요청 전체(파일 합계)에 걸리므로
 * 여러 파일을 한 요청에 담지 않고 파일마다 따로 보낸다.
 */
export async function uploadFile(file: File): Promise<string> {
  const form = new FormData()
  form.append('files', file)
  const result = await apiUpload<UploadResult>('/uploads', form, { timeoutMs: UPLOAD_TIMEOUT_MS })
  return result?.items?.[0]?.name ?? file.name
}

/** 서버 문구만으로는 무엇을 고칠지 알기 어려운 오류를 풀어 쓴다 (규약 §3.5) */
export function uploadProblem(e: Error): string {
  if (e instanceof ApiError && e.code === 'UNSUPPORTED_MEDIA') return '파일 내용이 wav, mp3가 아니거나 확장자와 달라요'
  if (hasValidationError(e, 'filename_invalid')) return '사용할 수 없는 파일 이름이에요. 이름을 바꿔서 다시 올려 주세요'
  return e.message
}
