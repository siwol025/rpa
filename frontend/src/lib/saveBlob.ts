export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  // 브라우저가 내려받기를 시작한 뒤에 해제한다
  setTimeout(() => URL.revokeObjectURL(url), 1_000)
}
