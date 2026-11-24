const pad = (n: number) => String(n).padStart(2, '0')

// API는 +09:00으로 주고받는다. 보는 PC의 시간대와 상관없이 한국 시간으로 보여준다.
const KST = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** '2026-11-20T10:30:00+09:00' → '2026-11-20T10:30' (datetime-local 입력칸 값), 없거나 잘못된 값이면 '' */
export function toInputValue(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = Object.fromEntries(KST.formatToParts(d).map((x) => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

export function fromInputValue(value: string): string | null {
  return value ? `${value}:00+09:00` : null
}

/** '2026-11-20T10:30:00+09:00' → '11/20 10:30' */
export function formatDateTime(iso: string | null): string {
  const v = toInputValue(iso)
  return v ? `${v.slice(5, 7)}/${v.slice(8, 10)} ${v.slice(11)}` : '-'
}

/** 389 → '6:29' */
export function formatSeconds(sec: number | null): string {
  if (sec === null) return '-'
  const s = Math.floor(sec)
  return `${Math.floor(s / 60)}:${pad(s % 60)}`
}
