export function ErrorState({ error, onRetry, retrying = false }: { error: Error; onRetry: () => void; retrying?: boolean }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg bg-crit-bg p-4 text-sm">
      <span>{error.message}</span>
      <button type="button" onClick={onRetry} disabled={retrying} className="btn">
        {retrying ? '불러오는 중' : '다시 시도'}
      </button>
    </div>
  )
}
