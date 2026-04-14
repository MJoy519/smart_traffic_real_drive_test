import React, { useState } from 'react'
import {
  MapPin, Zap, Heart, ChevronRight, ChevronLeft, LocateFixed,
  CheckCircle2, AlertCircle, Loader2, Clock, TestTube2,
} from 'lucide-react'
import clsx from 'clsx'
import RouteCard from './RouteCard'

const STEPS = ['select_origin', 'view_routes', 'select_time']
const STEP_LABELS = { select_origin: '选择起点', view_routes: '选择路线', select_time: '确认出行' }

// ── 起点选择卡片 ────────────────────────────────────────────────────
function OriginCard({ label, sublabel, icon: Icon, color, selected, onClick }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full text-left rounded-xl border-2 p-4 transition-all duration-200 focus:outline-none',
        selected
          ? `${color.border} ${color.bg} shadow-md`
          : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'
      )}
    >
      <div className="flex items-center gap-3">
        <div className={clsx('w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0', color.icon)}>
          <Icon size={20} className="text-white" />
        </div>
        <div>
          <div className="font-bold text-slate-800">{label}</div>
          <div className="text-xs text-slate-500 mt-0.5">{sublabel}</div>
        </div>
        {selected && <CheckCircle2 size={18} className={clsx('ml-auto flex-shrink-0', color.check)} />}
      </div>
    </button>
  )
}

// ── 模式切换按钮 ────────────────────────────────────────────────────
function ModeButton({ mode, selected, onClick, disabled }) {
  const isFast = mode === 'fast'
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex-1 flex items-center justify-center gap-2 py-3 rounded-xl border-2 font-semibold text-sm transition-all duration-200 focus:outline-none',
        selected
          ? isFast
            ? 'border-blue-500 bg-blue-500 text-white shadow-md'
            : 'border-purple-500 bg-purple-500 text-white shadow-md'
          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      {isFast ? <Zap size={16} /> : <Heart size={16} />}
      {isFast ? '快速路线' : '情感路线'}
    </button>
  )
}

/**
 * 控制面板主组件
 * 管理整个用户操作流程（起点 → 路线选择 → 出行时间 → 导航）
 */
export default function ControlPanel({
  // 状态
  step,
  mode,
  origin,
  selectedRouteKey,
  bestEmotionRoute,
  emotionResult,
  fastRoute,
  emotionRoute1,
  emotionRoute2,
  locationState,      // { loading, error, atOrigin }
  calculating,
  testMode,
  testModeRoute,

  // 回调
  onSelectOrigin,
  onSelectMode,
  onSelectRoute,
  onLocate,
  onCalculateEmotion,
  onConfirmNavigation,
  onStartNavigation,
  onBack,
}) {
  const [departureType, setDepartureType] = useState('now')  // 'now' | 'custom'
  const [customTime, setCustomTime] = useState('')

  const currentStepIndex = STEPS.indexOf(step)

  // 导航确认时把时间传出
  const handleConfirm = () => {
    const time = departureType === 'now' ? null : customTime || null
    onStartNavigation(time)
  }

  // ── 渲染拥堵指数（来自 emotionResult） ──────────────────────────
  const getCongestionIndex = (routeId) => {
    if (!emotionResult) return null
    const analysis = routeId === 1 ? emotionResult.route_1_analysis : emotionResult.route_2_analysis
    return analysis?.total_congestion_index ?? null
  }

  return (
    <div className="absolute top-4 left-4 bottom-4 z-20 w-[360px] flex flex-col pointer-events-none">
      <div className="flex flex-col h-full bg-white rounded-2xl shadow-2xl border border-slate-100 overflow-hidden pointer-events-auto">

        {/* ── 顶部 Header ─────────────────────────────────────────── */}
        <div className="px-5 pt-5 pb-4 border-b border-slate-100 flex-shrink-0">
          <div className="flex items-center gap-2 mb-1">
            {/* 返回按钮（第2、3步显示） */}
            {step !== 'select_origin' && (
              <button
                onClick={onBack}
                className="w-8 h-8 rounded-lg border border-slate-200 flex items-center justify-center text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors flex-shrink-0"
                title="返回上一步"
              >
                <ChevronLeft size={17} />
              </button>
            )}
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0">
              <MapPin size={16} className="text-white" />
            </div>
            <span className="font-bold text-slate-800 text-lg">智慧交通导航</span>
            {testMode && (
              <span className="ml-auto flex items-center gap-1 text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">
                <TestTube2 size={11} />
                测试模式
              </span>
            )}
          </div>

          {/* 步骤指示器 */}
          <div className="flex items-center gap-1 mt-3">
            {STEPS.map((s, i) => (
              <React.Fragment key={s}>
                <div className="flex items-center gap-1">
                  <div className={clsx(
                    'w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold transition-colors',
                    i < currentStepIndex  ? 'bg-indigo-600 text-white' :
                    i === currentStepIndex ? 'bg-indigo-600 text-white ring-2 ring-indigo-200' :
                    'bg-slate-200 text-slate-400'
                  )}>
                    {i < currentStepIndex ? '✓' : i + 1}
                  </div>
                  <span className={clsx(
                    'text-xs font-medium',
                    i === currentStepIndex ? 'text-indigo-600' : 'text-slate-400'
                  )}>
                    {STEP_LABELS[s]}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div className={clsx('flex-1 h-0.5 mx-1', i < currentStepIndex ? 'bg-indigo-300' : 'bg-slate-200')} />
                )}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* ── 滚动内容区 ──────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto custom-scroll px-5 py-4 space-y-4">

          {/* ═══ STEP 1: 选择起点 ═══════════════════════════════════ */}
          {step === 'select_origin' && (
            <div className="space-y-3">
              <p className="text-slate-600 text-sm">请选择本次行程的起点：</p>
              <OriginCard
                label="数码港"
                sublabel="HK Electric Charging Station, 100 Information Cres"
                icon={MapPin}
                color={{ border: 'border-indigo-500', bg: 'bg-indigo-50', icon: 'bg-indigo-500', check: 'text-indigo-500' }}
                selected={origin === 'cyberport'}
                onClick={() => onSelectOrigin('cyberport')}
              />
              <OriginCard
                label="马鞍山"
                sublabel="马鞍山游泳池, 鞍駿街33號"
                icon={MapPin}
                color={{ border: 'border-rose-500', bg: 'bg-rose-50', icon: 'bg-rose-500', check: 'text-rose-500' }}
                selected={origin === 'ma_on_shan'}
                onClick={() => onSelectOrigin('ma_on_shan')}
              />
            </div>
          )}

          {/* ═══ STEP 2: 查看路线 + 选择模式 ════════════════════════ */}
          {step === 'view_routes' && (
            <div className="space-y-4">
              {/* 模式选择 */}
              <div>
                <p className="text-sm font-medium text-slate-600 mb-2">导航模式</p>
                <div className="flex gap-2">
                  <ModeButton mode="fast"    selected={mode === 'fast'}    onClick={() => onSelectMode('fast')} />
                  <ModeButton mode="emotion" selected={mode === 'emotion'} onClick={() => onSelectMode('emotion')} />
                </div>
              </div>

              {/* 路线卡片列表 */}
              <div>
                <p className="text-sm font-medium text-slate-600 mb-2">所有路线</p>
                <div className="space-y-2">
                  {/* Fast 路线 */}
                  <RouteCard
                    routeKey="fast"
                    directionsResult={fastRoute}
                    isSelected={selectedRouteKey === 'fast'}
                    isRecommended={false}
                    onClick={() => mode === 'fast' && onSelectRoute('fast')}
                    disabled={mode !== 'fast'}
                  />
                  {/* Emotion 路线 1 */}
                  <RouteCard
                    routeKey="emotion1"
                    directionsResult={emotionRoute1}
                    isSelected={selectedRouteKey === 'emotion1'}
                    isRecommended={bestEmotionRoute === 1}
                    congestionIndex={getCongestionIndex(1)}
                    onClick={() => mode === 'emotion' && onSelectRoute('emotion1')}
                    disabled={mode !== 'emotion'}
                  />
                  {/* Emotion 路线 2 */}
                  <RouteCard
                    routeKey="emotion2"
                    directionsResult={emotionRoute2}
                    isSelected={selectedRouteKey === 'emotion2'}
                    isRecommended={bestEmotionRoute === 2}
                    congestionIndex={getCongestionIndex(2)}
                    onClick={() => mode === 'emotion' && onSelectRoute('emotion2')}
                    disabled={mode !== 'emotion'}
                  />
                </div>
              </div>

              {/* 情感模式 - 位置检测 + 计算 */}
              {mode === 'emotion' && (
                <div className="rounded-xl border border-purple-200 bg-purple-50 p-3 space-y-2">
                  <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide">情感路线计算</p>

                  {/* 位置状态 */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm">
                      {locationState.atOrigin ? (
                        <CheckCircle2 size={15} className="text-emerald-500" />
                      ) : locationState.error ? (
                        <AlertCircle size={15} className="text-red-400" />
                      ) : (
                        <div className="w-4 h-4 rounded-full border-2 border-slate-300" />
                      )}
                      <span className="text-slate-700">
                        {locationState.atOrigin
                          ? '已到达起点'
                          : locationState.error
                          ? locationState.error
                          : '尚未验证位置'}
                      </span>
                    </div>
                    <button
                      onClick={onLocate}
                      disabled={locationState.loading}
                      className="flex items-center gap-1 text-xs bg-white border border-purple-300 text-purple-600 px-2.5 py-1.5 rounded-lg hover:bg-purple-100 transition-colors disabled:opacity-50"
                    >
                      {locationState.loading
                        ? <Loader2 size={12} className="animate-spin" />
                        : <LocateFixed size={12} />}
                      {locationState.loading ? '定位中' : '检查位置'}
                    </button>
                  </div>

                  {/* 计算结果 */}
                  {emotionResult && !emotionResult.test_mode && (
                    <div className="text-xs text-slate-600 bg-white rounded-lg p-2">
                      {emotionResult.reason}
                    </div>
                  )}
                  {emotionResult?.test_mode && (
                    <div className="text-xs text-amber-600 bg-amber-50 rounded-lg p-2 flex items-center gap-1">
                      <TestTube2 size={11} />
                      {emotionResult.reason}
                    </div>
                  )}

                  {/* 计算按钮 */}
                  <button
                    onClick={onCalculateEmotion}
                    disabled={calculating || (!locationState.atOrigin && !testMode)}
                    className={clsx(
                      'w-full flex items-center justify-center gap-2 py-2.5 rounded-xl font-semibold text-sm transition-colors',
                      calculating || (!locationState.atOrigin && !testMode)
                        ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                        : 'bg-purple-600 hover:bg-purple-700 text-white'
                    )}
                  >
                    {calculating
                      ? <><Loader2 size={15} className="animate-spin" /> 计算中...</>
                      : <><Zap size={15} /> 计算最优情感路线</>}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ═══ STEP 3: 选择出行时间 ════════════════════════════════ */}
          {step === 'select_time' && (
            <div className="space-y-4">
              {/* 当前选中路线摘要 */}
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                <p className="text-xs text-slate-500 mb-1">已选路线</p>
                <RouteCard
                  routeKey={selectedRouteKey}
                  directionsResult={
                    selectedRouteKey === 'fast'     ? fastRoute     :
                    selectedRouteKey === 'emotion1' ? emotionRoute1 : emotionRoute2
                  }
                  isSelected={true}
                  isRecommended={
                    (selectedRouteKey === 'emotion1' && bestEmotionRoute === 1) ||
                    (selectedRouteKey === 'emotion2' && bestEmotionRoute === 2)
                  }
                  congestionIndex={
                    selectedRouteKey === 'emotion1' ? getCongestionIndex(1) :
                    selectedRouteKey === 'emotion2' ? getCongestionIndex(2) : null
                  }
                  disabled
                />
              </div>

              {/* 出发时间 */}
              <div>
                <p className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-1.5">
                  <Clock size={15} className="text-slate-400" />
                  预计出发时间
                </p>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <button
                    onClick={() => setDepartureType('now')}
                    className={clsx(
                      'py-2.5 rounded-xl border-2 text-sm font-semibold transition-all',
                      departureType === 'now'
                        ? 'border-indigo-500 bg-indigo-500 text-white'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                    )}
                  >
                    立即出发
                  </button>
                  <button
                    onClick={() => setDepartureType('custom')}
                    className={clsx(
                      'py-2.5 rounded-xl border-2 text-sm font-semibold transition-all',
                      departureType === 'custom'
                        ? 'border-indigo-500 bg-indigo-500 text-white'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                    )}
                  >
                    指定时间
                  </button>
                </div>
                {departureType === 'custom' && (
                  <input
                    type="datetime-local"
                    value={customTime}
                    onChange={(e) => setCustomTime(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── 底部操作按钮 ─────────────────────────────────────────── */}
        <div className="px-5 pb-5 pt-3 border-t border-slate-100 flex-shrink-0 space-y-2">
          {step === 'select_origin' && (
            <button
              onClick={() => onConfirmNavigation()}
              disabled={!origin}
              className={clsx(
                'w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-all',
                origin
                  ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              )}
            >
              下一步
              <ChevronRight size={16} />
            </button>
          )}

          {step === 'view_routes' && (
            <button
              onClick={() => onConfirmNavigation()}
              disabled={!selectedRouteKey}
              className={clsx(
                'w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-all',
                selectedRouteKey
                  ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              )}
            >
              选择出行时间
              <ChevronRight size={16} />
            </button>
          )}

          {step === 'select_time' && (
            <button
              onClick={handleConfirm}
              disabled={departureType === 'custom' && !customTime}
              className={clsx(
                'w-full flex items-center justify-center gap-2 py-3.5 rounded-xl font-bold text-sm transition-all',
                (departureType !== 'custom' || customTime)
                  ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-md'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              )}
            >
              开始导航
              <ChevronRight size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
