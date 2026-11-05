'use client'

import React from 'react'

// ── Skeleton grid row ─────────────────────────────────────────────────────────
function SkeletonRow({ cols }: { cols: number }) {
  return (
    <tr className="border-b border-slate-800">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-3 py-2">
          <div className="h-3 rounded bg-slate-700 animate-pulse" style={{ width: `${55 + (i % 4) * 12}%` }} />
        </td>
      ))}
    </tr>
  )
}

interface SkeletonGridProps {
  rows?: number
  cols?: number
}

export function SkeletonGrid({ rows = 10, cols = 8 }: SkeletonGridProps) {
  return (
    <div className="overflow-hidden rounded border border-slate-700">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-700 bg-slate-800/60">
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i} className="px-3 py-2 text-left">
                <div className="h-3 w-16 rounded bg-slate-600 animate-pulse" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, i) => (
            <SkeletonRow key={i} cols={cols} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Full-tab loading overlay ──────────────────────────────────────────────────
interface FullTabLoaderProps {
  message?: string
}

export function FullTabLoader({ message = 'Loading…' }: FullTabLoaderProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-slate-500">
      <svg className="h-8 w-8 animate-spin text-amber-500" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
      </svg>
      <span className="font-mono text-xs">{message}</span>
    </div>
  )
}
