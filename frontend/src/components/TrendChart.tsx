import { useState } from 'react'
import type { Granularity, TrendItem } from '../api/types'
import { axisLabel, fillBuckets, periodLabel } from '../lib/trend'

const W = 640
const H = 236
const LEFT = 30
const RIGHT = 6
const TOP = 10
const BOTTOM = 26
const PLOT_W = W - LEFT - RIGHT
const PLOT_H = H - TOP - BOTTOM
const MAX_LABELS = 9

export function TrendChart({ items, granularity }: { items: TrendItem[]; granularity: Granularity }) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null)
  const rows = fillBuckets(items, granularity)
  const max = Math.max(1, ...rows.map((r) => r.count))
  const step = Math.max(1, Math.ceil(max / 4))
  const top = Math.ceil(max / step) * step
  const ticks = Array.from({ length: top / step + 1 }, (_, i) => i * step)
  const y = (v: number) => TOP + PLOT_H - (v / top) * PLOT_H
  const slot = PLOT_W / rows.length
  const bar = Math.min(34, Math.max(1, slot * 0.6))
  const r = Math.min(4, bar / 2)
  const every = Math.ceil(rows.length / MAX_LABELS)
  const text = (row: TrendItem) => `${periodLabel(row.period, granularity)} ${row.count}건`
  const summary = rows.filter((row) => row.count > 0).map(text).join(', ')

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`기간별 상담 건수: ${summary}`} className="block h-auto w-full" onMouseLeave={() => setTip(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={LEFT} x2={W - RIGHT} y1={y(v)} y2={y(v)} stroke={v ? 'var(--grid)' : 'var(--axis)'} />
            <text x={LEFT - 8} y={y(v) + 4} textAnchor="end" className="num fill-muted text-[11px]">
              {v}
            </text>
          </g>
        ))}
        {rows.map((row, i) => {
          const x = LEFT + slot * i + (slot - bar) / 2
          return (
            <g key={row.period} onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, text: text(row) })}>
              {row.count > 0 && (
                <path fill="var(--s1)" d={`M${x},${y(0)} V${y(row.count) + r} q0,${-r} ${r},${-r} H${x + bar - r} q${r},0 ${r},${r} V${y(0)} Z`} />
              )}
              {i % every === 0 && (
                <text x={LEFT + slot * (i + 0.5)} y={H - 8} textAnchor="middle" className="num fill-muted text-[11px]">
                  {axisLabel(row.period, granularity)}
                </text>
              )}
              <rect x={LEFT + slot * i} y={TOP} width={slot} height={PLOT_H} fill="transparent" />
            </g>
          )
        })}
      </svg>
      {tip && (
        <div className="pointer-events-none fixed z-50 rounded-md bg-fg px-2.5 py-1.5 text-xs whitespace-nowrap text-bg" style={{ left: Math.min(tip.x + 12, window.innerWidth - 150), top: tip.y + 14 }}>
          {tip.text}
        </div>
      )}
    </>
  )
}
