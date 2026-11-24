// 서버 설정(ALLOWED_EXTENSIONS, MAX_UPLOAD_MB)의 기본값과 같다. 최종 판단은 서버가 한다.
export const ALLOWED_EXTENSIONS = ['wav', 'mp3']
export const MAX_UPLOAD_MB = 100

/** 올릴 수 없으면 이유, 올릴 수 있으면 null */
export function checkFile(file: { name: string; size: number }): string | null {
  const ext = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : ''
  if (!ALLOWED_EXTENSIONS.includes(ext)) return `지원하지 않는 형식이에요. ${ALLOWED_EXTENSIONS.join(', ')} 파일만 올릴 수 있어요`
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `파일이 너무 커요. ${MAX_UPLOAD_MB}MB까지 올릴 수 있어요`
  return null
}
