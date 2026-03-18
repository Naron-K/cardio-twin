import { createContext, useContext, useState, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

interface ToastItem {
  id: string
  message: string
  type: ToastType
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: string) => {
    clearTimeout(timers.current.get(id))
    timers.current.delete(id)
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback(
    (message: string, type: ToastType = 'info') => {
      const id = crypto.randomUUID()
      setToasts((prev) => [...prev, { id, message, type }])
      const timer = setTimeout(() => dismiss(id), 4000)
      timers.current.set(id, timer)
    },
    [dismiss]
  )

  const colorClass: Record<ToastType, string> = {
    success: 'bg-emerald-900/90 border-emerald-700 text-emerald-200',
    error: 'bg-red-900/90 border-red-700 text-red-200',
    warning: 'bg-yellow-900/90 border-yellow-700 text-yellow-200',
    info: 'bg-slate-700/90 border-slate-600 text-slate-200',
  }

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {/* Toast container — fixed bottom-right */}
      <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg text-sm max-w-sm border pointer-events-auto ${colorClass[t.type]}`}
          >
            <span className="flex-1 leading-snug">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="opacity-60 hover:opacity-100 leading-none text-base shrink-0"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
