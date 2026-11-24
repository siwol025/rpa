import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ToastContext } from '../lib/toast'

const SHOW_MS = 3_000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string } | null>(null)
  const show = useCallback((message: string) => setToast({ message }), [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), SHOW_MS)
    return () => clearTimeout(t)
  }, [toast])

  return (
    <ToastContext value={show}>
      {children}
      <div role="status" className="pointer-events-none fixed inset-x-4 bottom-6 z-50 flex justify-center">
        {toast && <span className="rounded-lg bg-fg px-4 py-2.5 text-[13px] font-medium text-bg">{toast.message}</span>}
      </div>
    </ToastContext>
  )
}
