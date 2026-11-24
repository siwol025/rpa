import { apiUpload } from './client'

const UPLOAD_TIMEOUT_MS = 5 * 60_000

/**
 * 파일 하나를 올린다. 서버의 크기 제한은 요청 전체(파일 합계)에 걸리므로
 * 여러 파일을 한 요청에 담지 않고 파일마다 따로 보낸다.
 */
export function uploadFile(file: File): Promise<void> {
  const form = new FormData()
  form.append('files', file) // [확인 필요] 폼 필드 이름
  return apiUpload('/uploads', form, { timeoutMs: UPLOAD_TIMEOUT_MS })
}
