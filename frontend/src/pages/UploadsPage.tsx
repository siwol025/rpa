import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { MONITOR_SIZE, useMonitor, useRetryCall } from '../api/calls'
import { uploadFile } from '../api/uploads'
import type { CallListItem } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { Badge, StatusBadges } from '../components/StatusBadge'
import { formatDateTime } from '../lib/format'
import { canRetry } from '../lib/status'
import { useToast } from '../lib/toast'
import { ALLOWED_EXTENSIONS, checkFile, MAX_UPLOAD_MB } from '../lib/upload'

interface Item {
  key: number
  name: string
  state: 'uploading' | 'done' | 'failed'
  message: string
}

let nextKey = 0

function Uploader() {
  const [items, setItems] = useState<Item[]>([])
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  // 한 번에 하나씩 순서대로 보낸다 (큰 녹취를 동시에 올리지 않도록)
  const queue = useRef<Promise<void>>(Promise.resolve())

  const update = (key: number, patch: Partial<Item>) => setItems((list) => list.map((i) => (i.key === key ? { ...i, ...patch } : i)))

  const add = (files: FileList | File[]) => {
    const added = [...files].map((file) => {
      const reason = checkFile(file)
      const item: Item = { key: nextKey++, name: file.name, state: reason ? 'failed' : 'uploading', message: reason ?? '올리는 중' }
      return { file, item }
    })
    setItems((list) => [...added.map((a) => a.item), ...list])
    for (const { file, item } of added) {
      if (item.state === 'failed') continue
      queue.current = queue.current.then(async () => {
        try {
          await uploadFile(file)
          update(item.key, { state: 'done', message: '접수됨, 처리 대기' })
        } catch (e) {
          update(item.key, { state: 'failed', message: (e as Error).message })
        }
      })
    }
  }

  const tone = { uploading: 'running', done: 'done', failed: 'failed' } as const
  return (
    <section aria-label="음성 파일 업로드" className="panel">
      <h2 className="m-0 text-[15px] font-semibold">음성 파일 업로드</h2>
      <p className="mt-0.5 mb-3 text-xs text-muted">
        {ALLOWED_EXTENSIONS.join(', ')} · 최대 {MAX_UPLOAD_MB}MB · 여러 파일을 함께 올릴 수 있어요
      </p>
      <div
        className={`flex flex-col items-center gap-2 rounded-lg border-[1.5px] border-dashed px-4 py-6 text-center ${over ? 'border-s1 bg-accent-soft' : 'border-line-strong'}`}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          add(e.dataTransfer.files)
        }}
      >
        <span>파일을 여기에 끌어다 놓으세요</span>
        <button type="button" className="btn btn-primary" onClick={() => input.current?.click()}>
          파일 선택
        </button>
        <input
          ref={input}
          type="file"
          aria-label="음성 파일"
          multiple
          hidden
          accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(',')}
          onChange={(e) => {
            if (e.target.files) add(e.target.files)
            e.target.value = '' // 같은 파일을 다시 고를 수 있게
          }}
        />
      </div>
      <ul aria-label="업로드 결과" aria-live="polite" className="mt-3 mb-0 list-none p-0 text-[13px]">
        {items.map((i) => (
          <li key={i.key} className="flex flex-wrap justify-between gap-x-3.5 gap-y-1.5 border-t border-line py-2">
            <span className="break-all">{i.name}</span>
            <Badge tone={tone[i.state]}>{i.message}</Badge>
          </li>
        ))}
      </ul>
    </section>
  )
}

function RetryCell({ call }: { call: CallListItem }) {
  const retry = useRetryCall()
  const toast = useToast()
  if (!canRetry(call.status, call.stale)) return <span className="text-muted">{call.stale ? '로봇 점검 필요' : '-'}</span>
  return (
    <button
      type="button"
      className="btn"
      disabled={retry.isPending}
      onClick={() => retry.mutate(call.id, { onSuccess: () => toast('재처리를 요청했어요. 다음 처리 주기에 반영돼요'), onError: (e) => toast(e.message) })}
    >
      재처리 요청
    </button>
  )
}

function Monitor() {
  const queries = useMonitor()
  const failed = queries.find((q) => q.error)
  const loaded = queries.every((q) => q.data)
  const rows = queries.flatMap((q) => q.data?.items ?? []).sort((a, b) => Date.parse(b.status_changed_at) - Date.parse(a.status_changed_at))
  const hidden = queries.reduce((n, q) => n + (q.data ? Math.max(0, q.data.total - q.data.items.length) : 0), 0)
  const stale = rows.filter((c) => c.stale).length

  return (
    <section aria-label="처리 상태" className="mt-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2.5">
        <h2 className="m-0 text-[15px] font-semibold">처리 상태</h2>
        {loaded && !failed && <span className="text-xs text-muted">자동으로 갱신돼요</span>}
      </div>
      {failed?.error && (
        <div className="mb-3">
          <ErrorState error={failed.error} onRetry={() => queries.forEach((q) => q.error && q.refetch())} retrying={failed.isFetching} />
        </div>
      )}
      {stale > 0 && (
        <div className="alert mb-3">
          <span>오래 처리가 멈춘 상담이 {stale}건 있어요</span>
        </div>
      )}
      {loaded ? (
        <div className="tablewrap">
          <table className="min-w-[700px]">
            <thead>
              <tr>
                {['파일', '처리 상태', '상태 변경', '재처리 횟수', '재처리'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/calls/${c.id}`} className="text-fg underline">
                      {c.original_name}
                    </Link>
                  </td>
                  <td>
                    <StatusBadges call={c} metadata={false} />
                  </td>
                  <td className="num whitespace-nowrap">{formatDateTime(c.status_changed_at)}</td>
                  <td className="num">{c.retry_count}</td>
                  <td>
                    <RetryCell call={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && hidden === 0 && <EmptyState title="처리 중인 상담이 없어요" />}
        </div>
      ) : (
        !failed && <div aria-label="불러오는 중" role="status" className="skeleton h-40" />
      )}
      {hidden > 0 && (
        <p className="mt-2 mb-0 text-[13px] text-fg-2">
          상태마다 {MONITOR_SIZE}건까지 보여줘요. {hidden}건이 더 있어요. <Link to="/calls" className="underline">상담 목록에서 보기</Link>
        </p>
      )}
    </section>
  )
}

export function UploadsPage() {
  return (
    <>
      <h1 className="m-0 mb-4 text-[22px] font-bold tracking-tight">업로드·처리 상태</h1>
      <Uploader />
      <Monitor />
    </>
  )
}
