'use client'

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  ReactNode,
  useEffect,
} from 'react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id:      string
  message: string
  type:    ToastType
  ttl:     number   // ms until auto-dismiss
}

interface ToastCtx {
  toasts:   Toast[]
  addToast: (message: string, type?: ToastType, ttl?: number) => void
  dismiss:  (id: string) => void
}

// ── Context ───────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastCtx | undefined>(undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const counterRef = useRef(0)

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const addToast = useCallback(
    (message: string, type: ToastType = 'info', ttl = 4500) => {
      const id = `toast-${Date.now()}-${++counterRef.current}`
      setToasts(prev => [...prev.slice(-4), { id, message, type, ttl }]) // max 5 toasts
    },
    [],
  )

  return (
    <ToastContext.Provider value={{ toasts, addToast, dismiss }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be inside ToastProvider')
  return ctx
}

// ── Toast container (renders in top-right corner) ─────────────────────────────

const TYPE_STYLES: Record<ToastType, string> = {
  success: 'border-emerald-600/60 bg-emerald-950/90 text-emerald-300',
  error:   'border-rose-600/60    bg-rose-950/90    text-rose-300',
  warning: 'border-amber-600/60  bg-amber-950/90   text-amber-300',
  info:    'border-indigo-600/60  bg-indigo-950/90  text-indigo-300',
}

const TYPE_ICONS: Record<ToastType, string> = {
  success: '✓',
  error:   '✕',
  warning: '⚠',
  info:    'ℹ',
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const fadeTimer = setTimeout(() => setVisible(false), toast.ttl - 300)
    const removeTimer = setTimeout(() => onDismiss(toast.id), toast.ttl)
    return () => { clearTimeout(fadeTimer); clearTimeout(removeTimer) }
  }, [toast, onDismiss])

  return (
    <div
      className={clsx(
        'flex items-start gap-3 px-4 py-3 rounded-xl border text-sm font-mono shadow-2xl transition-all duration-300',
        TYPE_STYLES[toast.type],
        visible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-4',
      )}
      style={{ maxWidth: 380, backdropFilter: 'blur(12px)' }}
    >
      <span className="text-base font-black shrink-0 mt-0.5">{TYPE_ICONS[toast.type]}</span>
      <span className="flex-1 leading-5 break-words">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 opacity-50 hover:opacity-100 transition-opacity text-xs mt-0.5"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  )
}

function ToastContainer({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (!toasts.length) return null
  return (
    <div
      className="fixed right-4 z-[9999] flex flex-col gap-2 pointer-events-none"
      style={{ top: 'calc(var(--shell-top, 0px) + 16px)' }}
      aria-live="polite"
    >
      {toasts.map(t => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem toast={t} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  )
}
