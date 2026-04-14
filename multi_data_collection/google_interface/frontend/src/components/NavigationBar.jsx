import React, { useEffect, useState } from 'react'
import { MapPin, Clock, Navigation2, X, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'

const ROUTE_LABEL = {
  fast:     '最快路线',
  emotion1: '情感路线 1（北线）',
  emotion2: '情感路线 2（南线）',
}

const ROUTE_COLOR = {
  fast:     'text-blue-500',
  emotion1: 'text-emerald-500',
  emotion2: 'text-amber-500',
}

/**
 * 导航模式底部状态栏
 */
export default function NavigationBar({ activeRoute, directionsResult, saveStatus, onEnd }) {
  const leg = directionsResult?.routes?.[0]?.legs?.[0]
  const duration = leg?.duration_in_traffic?.text || leg?.duration?.text || '—'
  const distance = leg?.distance?.text || '—'
  const destination = leg?.end_address || '目的地'

  // saveStatus 提示条：3 秒后自动消隐
  const [showSave, setShowSave] = useState(!!saveStatus)
  useEffect(() => {
    if (saveStatus) {
      setShowSave(true)
      const t = setTimeout(() => setShowSave(false), 3000)
      return () => clearTimeout(t)
    }
  }, [saveStatus])

  return (
    <div className="absolute bottom-0 left-0 right-0 z-30 pointer-events-none">
      <div className="mx-4 mb-4 pointer-events-auto space-y-2">

        {/* 路线保存提示条 */}
        {showSave && saveStatus && (
          <div className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium shadow
            ${saveStatus === 'saving' ? 'bg-indigo-50 text-indigo-700 border border-indigo-200' :
              saveStatus === 'ok'     ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
                                       'bg-red-50 text-red-600 border border-red-200'}`}>
            {saveStatus === 'saving' && <Loader2 size={15} className="animate-spin flex-shrink-0" />}
            {saveStatus === 'ok'     && <CheckCircle2 size={15} className="flex-shrink-0" />}
            {saveStatus === 'error'  && <AlertCircle size={15} className="flex-shrink-0" />}
            {saveStatus === 'saving' ? '正在保存路线选择...' :
             saveStatus === 'ok'     ? '路线选择已记录到受试者文件夹' :
                                      '路线选择保存失败（请检查后端连接）'}
          </div>
        )}

        <div className="bg-white rounded-2xl shadow-2xl border border-slate-100 px-5 py-4">
          <div className="flex items-center justify-between gap-4">
            {/* 路线信息 */}
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <div className="w-10 h-10 rounded-full bg-indigo-50 flex items-center justify-center flex-shrink-0">
                <Navigation2 size={20} className="text-indigo-600" />
              </div>
              <div className="min-w-0">
                <div className={`text-xs font-semibold mb-0.5 ${ROUTE_COLOR[activeRoute] || 'text-indigo-500'}`}>
                  {ROUTE_LABEL[activeRoute] || '导航中'}
                </div>
                <div className="text-slate-700 text-sm font-medium truncate flex items-center gap-1">
                  <MapPin size={12} className="text-slate-400 flex-shrink-0" />
                  {destination}
                </div>
              </div>
            </div>

            {/* 时间 + 距离 */}
            <div className="flex items-center gap-4 flex-shrink-0">
              <div className="text-center">
                <div className="flex items-center gap-1 text-slate-800 font-bold text-lg">
                  <Clock size={15} className="text-slate-400" />
                  {duration}
                </div>
                <div className="text-xs text-slate-400">{distance}</div>
              </div>

              {/* 结束导航按钮 */}
              <button
                onClick={onEnd}
                className="flex items-center gap-1.5 bg-red-500 hover:bg-red-600 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
              >
                <X size={15} />
                结束
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
