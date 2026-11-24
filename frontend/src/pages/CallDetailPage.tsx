import { useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { audioUrl, useCall, useDeleteCall, useRetryCall, useUpdateCall } from '../api/calls'
import { ApiError } from '../api/client'
import { ACTION_STATUSES, CATEGORIES, type ActionStatus, type CallDetail, type CallPatch, type Category } from '../api/types'
import { CategoryChip } from '../components/CategoryChip'
import { ErrorState } from '../components/ErrorState'
import { Badge, StatusBadges } from '../components/StatusBadge'
import { formatDateTime, formatSeconds, fromInputValue, toInputValue } from '../lib/format'
import { ACTION_LABEL, canRetry, STEP_LABEL, type StatusTone } from '../lib/status'
import { useToast } from '../lib/toast'

const MASK = /([0-9A-Za-z-]*\*{3,}[0-9A-Za-z*-]*)/g

/** 가려진 개인정보(*** 포함)를 강조한다 */
function withMasks(text: string): ReactNode[] {
  return text.split(MASK).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="mask num">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="panel">
      <h2 className="m-0 mb-3 text-[15px] font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function Alert({ error }: { error: Error | null }) {
  if (!error) return null
  return (
    <p role="alert" className="m-0 rounded-md bg-crit-bg p-3 text-[13px] text-crit">
      {error.message}
    </p>
  )
}

function Header({ c }: { c: CallDetail }) {
  const items: [string, string][] = [
    ['통화 일시', formatDateTime(c.call_datetime)],
    ['담당자', c.agent_name ?? '-'],
    ['고객사', c.client_company ?? '-'],
    ['통화 시간', formatSeconds(c.duration_sec)],
    ['파일', c.original_name],
    ['입력', c.source_type === 'WEB' ? '웹 업로드' : '클라우드 폴더'],
  ]
  return (
    <section aria-label="상담 정보" className="mb-4 flex flex-col gap-2">
      <h1 className="m-0 text-[22px] font-bold tracking-tight">상담 {c.id}</h1>
      <span className="inline-flex flex-wrap gap-1">
        {c.analysis && <CategoryChip category={c.analysis.category} />}
        <StatusBadges call={c} />
      </span>
      <dl className="num m-0 flex flex-wrap gap-x-[18px] gap-y-1 text-[13px]">
        {items.map(([k, v]) => (
          <div key={k} className="flex gap-1.5">
            <dt className="text-muted">{k}</dt>
            <dd className="m-0 break-all">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function Transcript({ c }: { c: CallDetail }) {
  if (!c.transcript) return <p className="notice">{c.status === 'FAILED' ? '전사에 실패했어요.' : '아직 전사되지 않았어요.'}</p>
  return (
    <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
      {c.transcript.segments.map((s, i) => {
        const agent = s.speaker === 'AGENT'
        return (
          <li key={i} className={`flex max-w-[84%] flex-col gap-0.5 ${agent ? 'items-start self-start' : 'items-end self-end'}`}>
            <span className="num text-[11px] font-medium text-muted">{`${agent ? '상담원' : '고객'} · ${formatSeconds(s.start)}`}</span>
            <div className={`rounded-[10px] px-3 py-2 text-[13.5px] leading-relaxed ${agent ? 'rounded-tl-sm bg-accent-soft' : 'rounded-tr-sm bg-surface-2'}`}>{withMasks(s.text)}</div>
          </li>
        )
      })}
    </ul>
  )
}

const LOG: Record<string, [label: string, tone: StatusTone]> = { SUCCESS: ['성공', 'done'], FAIL: ['실패', 'failed'], RETRY: ['재시도', 'warn'] }

function Logs({ c }: { c: CallDetail }) {
  return (
    <ul className="m-0 list-none p-0 text-[13px]">
      {c.processing_log.map((l, i) => {
        const [label, tone] = LOG[l.status] ?? [l.status, 'running']
        return (
          <li key={i} className="grid grid-cols-[72px_auto_minmax(0,1fr)_auto] items-center gap-2.5 border-t border-line py-1.5 first:border-t-0">
            <span>{STEP_LABEL[l.step] ?? l.step}</span>
            <Badge tone={tone}>{label}</Badge>
            <span className="break-words">{l.message}</span>
            <span className="num text-muted">{formatDateTime(l.created_at)}</span>
          </li>
        )
      })}
    </ul>
  )
}

interface FormValues {
  category: Category | ''
  action_status: ActionStatus | ''
  question_summary: string
  action_summary: string
  agent_name: string
  client_company: string
  call_datetime: string
}

function toForm(c: CallDetail): FormValues {
  return {
    category: c.analysis?.category ?? '',
    action_status: c.analysis?.action_status ?? '',
    question_summary: c.analysis?.question_summary ?? '',
    action_summary: c.analysis?.action_summary ?? '',
    agent_name: c.agent_name ?? '',
    client_company: c.client_company ?? '',
    call_datetime: toInputValue(c.call_datetime),
  }
}

/** 바뀐 값만 담는다. 건드리지 않은 값을 덮어쓰지 않기 위해서다 */
function diff(before: FormValues, now: FormValues): CallPatch {
  const p: CallPatch = {}
  if (now.category && now.category !== before.category) p.category = now.category
  if (now.action_status && now.action_status !== before.action_status) p.action_status = now.action_status
  if (now.question_summary !== before.question_summary) p.question_summary = now.question_summary
  if (now.action_summary !== before.action_summary) p.action_summary = now.action_summary
  if (now.agent_name.trim() !== before.agent_name) p.agent_name = now.agent_name.trim() || null
  if (now.client_company.trim() !== before.client_company) p.client_company = now.client_company.trim() || null
  if (now.call_datetime !== before.call_datetime) p.call_datetime = fromInputValue(now.call_datetime)
  return p
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-fg-2">
        {label}
      </label>
      {children}
    </div>
  )
}

function AnalysisFacts({ c }: { c: CallDetail }) {
  const a = c.analysis!
  const rows: [string, string][] = [
    ['신뢰도', a.confidence === null ? '-' : Number(a.confidence).toFixed(2)],
    ['후속 조치', a.follow_up_required ? '필요' : '필요 없음'],
  ]
  for (const [label, list] of [
    ['제품·서비스', a.entities?.products],
    ['일정', a.entities?.dates],
    ['키워드', a.entities?.keywords],
  ] as const) {
    if (list?.length) rows.push([label, list.join(', ')])
  }
  return (
    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3.5 gap-y-1 text-[13px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="num m-0">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function EditForm({ c }: { c: CallDetail }) {
  // 처음 한 번만 채운다. 다시 불러와도 저장하지 않은 입력을 지우지 않는다.
  const [saved, setSaved] = useState(() => toForm(c))
  const [form, setForm] = useState(saved)
  const [editor, setEditor] = useState('')
  const update = useUpdateCall(c.id)
  const toast = useToast()
  const bind = <K extends keyof FormValues>(key: K) => ({
    id: `f-${key}`,
    className: 'field w-full',
    value: form[key],
    onChange: (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value })),
  })
  const changes = diff(saved, form)
  const dirty = Object.keys(changes).length > 0

  const submit = (extra: CallPatch, done: string) => {
    const patch: CallPatch = { ...changes, ...extra }
    if (editor.trim()) patch.editor = editor.trim()
    update.mutate(patch, {
      onSuccess: () => {
        setSaved(form)
        toast(done)
      },
    })
  }

  return (
    <form
      className="flex flex-col gap-3.5"
      onSubmit={(e) => {
        e.preventDefault()
        if (dirty) submit({}, '저장했어요')
      }}
    >
      {c.analysis ? (
        <>
          {c.status === 'NEEDS_REVIEW' && <p className="m-0 rounded-md bg-review-bg p-3 text-[13px] text-review">분류 신뢰도가 낮아 검토가 필요해요.</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="f-category" label="유형">
              <select {...bind('category')}>
                {CATEGORIES.map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </Field>
            <Field id="f-action_status" label="조치 상태">
              <select {...bind('action_status')}>
                {ACTION_STATUSES.map((k) => (
                  <option key={k} value={k}>
                    {ACTION_LABEL[k]}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field id="f-question_summary" label="질문 요약">
            <textarea rows={3} {...bind('question_summary')} />
          </Field>
          <Field id="f-action_summary" label="조치 내역">
            <textarea rows={3} {...bind('action_summary')} />
          </Field>
          <AnalysisFacts c={c} />
        </>
      ) : (
        <p className="notice">{c.status === 'FAILED' && c.transcript ? 'AI 분석에 실패했어요. 처리 이력에서 사유를 확인해 주세요.' : '아직 분석 결과가 없어요.'}</p>
      )}
      <hr className="m-0 w-full border-0 border-t border-line" />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="f-agent_name" label="담당자">
          <input {...bind('agent_name')} maxLength={50} />
        </Field>
        <Field id="f-client_company" label="고객사">
          <input {...bind('client_company')} maxLength={100} />
        </Field>
        <Field id="f-call_datetime" label="통화 일시">
          <input type="datetime-local" {...bind('call_datetime')} />
        </Field>
        <Field id="f-editor" label="수정자 이름">
          <input id="f-editor" className="field w-full" autoComplete="off" maxLength={50} value={editor} onChange={(e) => setEditor(e.target.value)} />
        </Field>
      </div>
      <Alert error={update.error} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn btn-primary" disabled={!dirty || update.isPending}>
          저장
        </button>
        {c.status === 'NEEDS_REVIEW' && (
          <button type="button" className="btn" disabled={update.isPending} onClick={() => submit({ review_completed: true }, '검토를 완료했어요')}>
            검토 완료
          </button>
        )}
      </div>
    </form>
  )
}

function retryNotice(c: CallDetail): string {
  if (c.status !== 'RETRY_REQUESTED') return '처리 중인 상담은 재처리를 요청할 수 없어요.'
  return c.stale
    ? '재처리 요청이 오래 멈춰 있어요. RPA 담당자에게 로봇 점검을 요청해 주세요.'
    : '재처리를 기다리고 있어요. 다음 처리 주기에 반영돼요.'
}

function Actions({ c, backTo }: { c: CallDetail; backTo: string }) {
  const [confirming, setConfirming] = useState(false)
  const retry = useRetryCall()
  const remove = useDeleteCall()
  const toast = useToast()
  const navigate = useNavigate()
  const allowed = canRetry(c.status, c.stale)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn"
          disabled={!allowed || retry.isPending}
          onClick={() => retry.mutate(c.id, { onSuccess: () => toast('재처리를 요청했어요. 다음 처리 주기에 반영돼요') })}
        >
          재처리 요청
        </button>
        {!confirming && (
          <button type="button" className="btn text-crit" onClick={() => setConfirming(true)}>
            삭제
          </button>
        )}
      </div>
      {!allowed && <p className="notice">{retryNotice(c)}</p>}
      {confirming && (
        <div role="group" aria-label="삭제 확인" className="flex flex-wrap items-center gap-2.5 rounded-md bg-crit-bg p-3 text-[13px]">
          <span className="min-w-[150px] flex-1">이 상담을 삭제할까요?</span>
          <button
            type="button"
            className="btn text-crit"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(c.id, {
                onSuccess: () => {
                  toast('삭제했어요')
                  navigate(backTo)
                },
              })
            }
          >
            삭제
          </button>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>
            취소
          </button>
        </div>
      )}
      <Alert error={retry.error ?? remove.error} />
    </div>
  )
}

export function CallDetailPage() {
  const id = Number(useParams().id)
  const valid = Number.isInteger(id) && id > 0
  const from = (useLocation().state as { from?: string } | null)?.from ?? ''
  const backTo = `/calls${from}`
  const { data: c, error, isFetching, refetch } = useCall(id, valid)
  const missing = !valid || (error instanceof ApiError && error.status === 404)

  return (
    <section>
      <Link to={backTo} className="mb-2.5 inline-block text-[13px] text-fg-2 no-underline hover:underline">
        ← 상담 목록
      </Link>
      {missing ? (
        <p className="notice">없거나 삭제된 상담이에요.</p>
      ) : error && !c ? (
        <ErrorState error={error} onRetry={() => refetch()} retrying={isFetching} />
      ) : !c ? (
        <div aria-label="불러오는 중" role="status" className="flex flex-col gap-3">
          <div className="skeleton h-7 w-40" />
          <div className="skeleton h-5 w-2/3" />
          <div className="skeleton h-60" />
        </div>
      ) : (
        <>
          <Header c={c} />
          <div className="grid grid-cols-1 items-start gap-3 min-[900px]:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-3">
              <Panel title="원본 음성">
                <audio aria-label="원본 음성 재생" className="w-full" controls preload="none" src={audioUrl(c.id)} />
              </Panel>
              <Panel title="전사 원문">
                <Transcript c={c} />
              </Panel>
              <Panel title="처리 이력">
                <Logs c={c} />
              </Panel>
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <Panel title="분석 결과·메타데이터">
                {/* 다른 상담으로 가거나 분석 결과가 새로 생기면 입력칸을 새로 채운다 */}
                <EditForm key={`${c.id}-${c.analysis !== null}`} c={c} />
              </Panel>
              <Panel title="재처리·삭제">
                <Actions key={c.id} c={c} backTo={backTo} />
              </Panel>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
