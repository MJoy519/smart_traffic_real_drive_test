import React from 'react'
import { Clock, Navigation, TrendingUp, Award } from 'lucide-react'
import clsx from 'clsx'

const COLOR_MAP = {
  fast:     { dot: 'bg-blue-500',   border: 'border-blue-500',   text: 'text-blue-600',   bg: 'bg-blue-50'  },
  emotion1: { dot: 'bg-emerald-500', border: 'border-emerald-500', text: 'text-emerald-600', bg: 'bg-emerald-50' },
  emotion2: { dot: 'bg-amber-500',   border: 'border-amber-500',   text: 'text-amber-600',   bg: 'bg-amber-50'  },
}

const LABEL_MAP = {
  fast:     '最快路线',
  emotion1: '情感路线 1（北线）',
  emotion2: '情感路线 2（南线）',
}

/**
 * 单条路线信息卡片
 */
export default function RouteCard({
  routeKey,           // 'fast' | 'emotion1' | 'emotion2'
  directionsResult,   // Google Maps DirectionsResult | null
  isSelected,         // boolean
  isRecommended,      // boolean（仅情感路线推荐时显示角标）
  congestionIndex,    // number | null（拥堵指数，情感路线计算后显示）
  onClick,            // () => void
  disabled,           // boolean
}) {
  const c = COLOR_MAP[routeKey] || COLOR_MAP.fast
  const label = LABEL_MAP[routeKey]

  // 从 DirectionsResult 中读取时间和距离
  const leg = directionsResult?.routes?.[0]?.legs?.[0]
  const duration = leg?.duration_in_traffic?.text || leg?.duration?.text || '—'
  const distance = leg?.distance?.text || '—'

  return (
    <button
      onClick={onClick}
      disabled={disabled || !directionsResult}
      className={clsx(
        'w-full text-left rounded-xl border-2 p-3 transition-all duration-200',
        'focus:outline-none',
        isSelected
          ? [`${c.border} ${c.bg} route-card-selected shadow-md`]
          : ['border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'],
        (disabled || !directionsResult) && 'opacity-50 cursor-not-allowed'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        {/* 左侧：颜色点 + 路线名 */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className={clsx('w-3 h-3 rounded-full flex-shrink-0', c.dot)} />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-semibold text-slate-800 text-sm truncate">
                {label}
              </span>
              {isRecommended && (
                <span className="flex items-center gap-0.5 text-xs font-semibold text-emerald-600 bg-emerald-100 px-1.5 py-0.5 rounded-full flex-shrink-0">
                  <Award size={11} />
                  推荐
                </span>
              )}
            </div>
          </div>
        </div>

        {/* 右侧：时间 */}
        {directionsResult && (
          <div className="flex items-center gap-1 flex-shrink-0">
            <Clock size={13} className="text-slate-400" />
            <span className={clsx('text-sm font-bold', isSelected ? c.text : 'text-slate-700')}>
              {duration}
            </span>
          </div>
        )}
      </div>

      {/* 详细信息行 */}
      {directionsResult && (
        <div className="mt-1.5 flex items-center gap-3 pl-5">
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <Navigation size={11} />
            <span>{distance}</span>
          </div>
          {congestionIndex !== null && congestionIndex !== undefined && (
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <TrendingUp size={11} />
              <span>拥堵指数 {(congestionIndex * 100).toFixed(1)}%</span>
            </div>
          )}
        </div>
      )}

      {/* 加载中占位 */}
      {!directionsResult && (
        <div className="mt-1.5 pl-5">
          <div className="h-3 w-24 bg-slate-200 rounded animate-pulse" />
        </div>
      )}
    </button>
  )
}
