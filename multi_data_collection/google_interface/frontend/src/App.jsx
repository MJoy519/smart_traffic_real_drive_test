import React, { useState, useCallback, useEffect, useRef } from 'react'
import { useJsApiLoader } from '@react-google-maps/api'
import MapView from './components/MapView'
import ControlPanel from './components/ControlPanel'
import NavigationBar from './components/NavigationBar'
import { calculateEmotionRoute, getTrafficData, getTestModeConfig, saveRouteSelection } from './api/routeApi'
import { useGeolocation } from './hooks/useGeolocation'

const MAPS_LIBRARIES = ['places', 'geometry']

// ── 起终点坐标（新路线）──────────────────────────────────────
const _LOCATION_MAP_NEW = {
  cyberport:  { lat: 22.350840, lng: 114.198602 },  // 慈正村三号停车场
  ma_on_shan: { lat: 22.280687, lng: 114.154501 },  // 中央广场停车场
}
// ── 起终点坐标（旧路线）──────────────────────────────────────
const _LOCATION_MAP_OLD = {
  cyberport:  { lat: 22.262372, lng: 114.130906 },  // 数码港
  ma_on_shan: { lat: 22.426133, lng: 114.232172 },  // 马鞍山
}

// ── 途经点：新路线（3个途径点/方向）────────────────────────
const _ROUTE_WAYPOINTS_NEW = {
  emotion1: {
    cyberport: [
      { location: { lat: 22.342975, lng: 114.184378 }, stopover: false }, // 途径点1
      { location: { lat: 22.336127, lng: 114.134340 }, stopover: false }, // 途径点2
      { location: { lat: 22.289671, lng: 114.142490 }, stopover: false }, // 途径点3
    ],
    ma_on_shan: [
      { location: { lat: 22.288595, lng: 114.146323 }, stopover: false }, // 途径点1
      { location: { lat: 22.331573, lng: 114.136412 }, stopover: false }, // 途径点2
      { location: { lat: 22.342891, lng: 114.185151 }, stopover: false }, // 途径点3
    ],
  },
  emotion2: {
    cyberport: [
      { location: { lat: 22.336935, lng: 114.195173 }, stopover: false }, // 途径点1
      { location: { lat: 22.308405, lng: 114.232008 }, stopover: false }, // 途径点2
      { location: { lat: 22.291345, lng: 114.193027 }, stopover: false }, // 途径点3
    ],
    ma_on_shan: [
      { location: { lat: 22.281564, lng: 114.179711 }, stopover: false }, // 途径点1
      { location: { lat: 22.306780, lng: 114.233123 }, stopover: false }, // 途径点2
      { location: { lat: 22.340598, lng: 114.200265 }, stopover: false }, // 途径点3
    ],
  },
}

// ── 途经点：旧路线（数码港↔马鞍山，北线21节点/南线24节点）──
const _ROUTE_WAYPOINTS_OLD = {
  emotion1: {
    // 数码港 → 马鞍山（北线/西区隧道，R1P02–R1P20，19个中间点）
    cyberport: [
      { location: { lat: 22.261628, lng: 114.129182 }, stopover: false }, // R1P02 资讯道环岛
      { location: { lat: 22.268944, lng: 114.126322 }, stopover: false }, // R1P03 域多利道
      { location: { lat: 22.283978, lng: 114.127770 }, stopover: false }, // R1P04 西环
      { location: { lat: 22.290004, lng: 114.142283 }, stopover: false }, // R1P05 西环2
      { location: { lat: 22.307271, lng: 114.160691 }, stopover: false }, // R1P06 西环3
      { location: { lat: 22.310942, lng: 114.165993 }, stopover: false }, // R1P07 油麻地友翔道
      { location: { lat: 22.322586, lng: 114.199980 }, stopover: false }, // R1P08 启德承里道
      { location: { lat: 22.323409, lng: 114.201894 }, stopover: false }, // R1P09 启德承里道2
      { location: { lat: 22.325086, lng: 114.203905 }, stopover: false }, // R1P10 九龍灣啓祥道
      { location: { lat: 22.325585, lng: 114.209296 }, stopover: false }, // R1P11 九龍灣啓祥道2
      { location: { lat: 22.329290, lng: 114.211462 }, stopover: false }, // R1P12 九龍灣观塘道
      { location: { lat: 22.337611, lng: 114.205271 }, stopover: false }, // R1P13 彩虹邨
      { location: { lat: 22.379742, lng: 114.210209 }, stopover: false }, // R1P14 沙田
      { location: { lat: 22.402500, lng: 114.215227 }, stopover: false }, // R1P15 沙田2
      { location: { lat: 22.407389, lng: 114.221979 }, stopover: false }, // R1P16 马鞍山路
      { location: { lat: 22.410490, lng: 114.223537 }, stopover: false }, // R1P17 马鞍山路2
      { location: { lat: 22.415470, lng: 114.224661 }, stopover: false }, // R1P18 马鞍山路3
      { location: { lat: 22.421894, lng: 114.227245 }, stopover: false }, // R1P19 马鞍山路4
      { location: { lat: 22.424497, lng: 114.229463 }, stopover: false }, // R1P20 马鞍山路5
    ],
    // 马鞍山 → 数码港（R1M02–R1M27，25个中间点，R1M11已删除以满足API上限）
    ma_on_shan: [
      { location: { lat: 22.425347, lng: 114.229303 }, stopover: false }, // R1M02
      { location: { lat: 22.415367, lng: 114.225305 }, stopover: false }, // R1M04
      { location: { lat: 22.410818, lng: 114.224335 }, stopover: false }, // R1M05
      { location: { lat: 22.408494, lng: 114.223013 }, stopover: false }, // R1M06
      { location: { lat: 22.406104, lng: 114.221253 }, stopover: false }, // R1M07
      { location: { lat: 22.402029, lng: 114.215116 }, stopover: false }, // R1M08
      { location: { lat: 22.398498, lng: 114.211734 }, stopover: false }, // R1M09
      { location: { lat: 22.385822, lng: 114.210971 }, stopover: false }, // R1M10
      { location: { lat: 22.351383, lng: 114.208783 }, stopover: false }, // R1M12
      { location: { lat: 22.337807, lng: 114.205198 }, stopover: false }, // R1M13
      { location: { lat: 22.329070, lng: 114.211924 }, stopover: false }, // R1M14
      { location: { lat: 22.326621, lng: 114.212191 }, stopover: false }, // R1M15
      { location: { lat: 22.324912, lng: 114.203739 }, stopover: false }, // R1M16
      { location: { lat: 22.322170, lng: 114.199673 }, stopover: false }, // R1M17
      { location: { lat: 22.310765, lng: 114.164011 }, stopover: false }, // R1M18
      { location: { lat: 22.289683, lng: 114.142314 }, stopover: false }, // R1M19
      { location: { lat: 22.286623, lng: 114.131597 }, stopover: false }, // R1M20
      { location: { lat: 22.284292, lng: 114.129215 }, stopover: false }, // R1M21
      { location: { lat: 22.282780, lng: 114.129173 }, stopover: false }, // R1M22
      { location: { lat: 22.282231, lng: 114.125722 }, stopover: false }, // R1M23
      { location: { lat: 22.278704, lng: 114.117762 }, stopover: false }, // R1M24
      { location: { lat: 22.274493, lng: 114.118295 }, stopover: false }, // R1M25
      { location: { lat: 22.268057, lng: 114.127063 }, stopover: false }, // R1M26
      { location: { lat: 22.261970, lng: 114.129222 }, stopover: false }, // R1M27
    ],
  },
  emotion2: {
    // 数码港 → 马鞍山（南线/香港仔，R2P02–R2P25，24个中间点）
    cyberport: [
      { location: { lat: 22.261552, lng: 114.129331 }, stopover: false }, // R2P02
      { location: { lat: 22.256601, lng: 114.134217 }, stopover: false }, // R2P03
      { location: { lat: 22.253626, lng: 114.139241 }, stopover: false }, // R2P04
      { location: { lat: 22.252453, lng: 114.140569 }, stopover: false }, // R2P05
      { location: { lat: 22.249329, lng: 114.145521 }, stopover: false }, // R2P06
      { location: { lat: 22.248724, lng: 114.148298 }, stopover: false }, // R2P07
      { location: { lat: 22.281037, lng: 114.180360 }, stopover: false }, // R2P09
      { location: { lat: 22.305877, lng: 114.181442 }, stopover: false }, // R2P10
      { location: { lat: 22.319594, lng: 114.189718 }, stopover: false }, // R2P11
      { location: { lat: 22.324022, lng: 114.190175 }, stopover: false }, // R2P12
      { location: { lat: 22.324939, lng: 114.188900 }, stopover: false }, // R2P13
      { location: { lat: 22.328325, lng: 114.191990 }, stopover: false }, // R2P14
      { location: { lat: 22.335044, lng: 114.204417 }, stopover: false }, // R2P15
      { location: { lat: 22.333057, lng: 114.206211 }, stopover: false }, // R2P16
      { location: { lat: 22.336431, lng: 114.204085 }, stopover: false }, // R2P17
      { location: { lat: 22.379256, lng: 114.210347 }, stopover: false }, // R2P18
      { location: { lat: 22.402190, lng: 114.214835 }, stopover: false }, // R2P19
      { location: { lat: 22.407509, lng: 114.222026 }, stopover: false }, // R2P20
      { location: { lat: 22.411205, lng: 114.223708 }, stopover: false }, // R2P21
      { location: { lat: 22.414659, lng: 114.224492 }, stopover: false }, // R2P22
      { location: { lat: 22.422298, lng: 114.227422 }, stopover: false }, // R2P23
      { location: { lat: 22.424599, lng: 114.229425 }, stopover: false }, // R2P24
      { location: { lat: 22.425288, lng: 114.229006 }, stopover: false }, // R2P25
    ],
    // 马鞍山 → 数码港（R2M02–R2M24，23个中间点）
    ma_on_shan: [
      { location: { lat: 22.425347, lng: 114.229303 }, stopover: false }, // R2M02
      { location: { lat: 22.423862, lng: 114.229164 }, stopover: false }, // R2M03
      { location: { lat: 22.415367, lng: 114.225305 }, stopover: false }, // R2M04
      { location: { lat: 22.410818, lng: 114.224335 }, stopover: false }, // R2M05
      { location: { lat: 22.408494, lng: 114.223013 }, stopover: false }, // R2M06
      { location: { lat: 22.406104, lng: 114.221253 }, stopover: false }, // R2M07
      { location: { lat: 22.402029, lng: 114.215116 }, stopover: false }, // R2M08
      { location: { lat: 22.398498, lng: 114.211734 }, stopover: false }, // R2M09
      { location: { lat: 22.385817, lng: 114.211094 }, stopover: false }, // R2M10
      { location: { lat: 22.380817, lng: 114.208086 }, stopover: false }, // R2M11
      { location: { lat: 22.377942, lng: 114.203327 }, stopover: false }, // R2M12
      { location: { lat: 22.343509, lng: 114.179351 }, stopover: false }, // R2M13
      { location: { lat: 22.281975, lng: 114.181411 }, stopover: false }, // R2M15
      { location: { lat: 22.250005, lng: 114.176442 }, stopover: false }, // R2M16
      { location: { lat: 22.248876, lng: 114.147278 }, stopover: false }, // R2M17
      { location: { lat: 22.249278, lng: 114.145478 }, stopover: false }, // R2M18
      { location: { lat: 22.252528, lng: 114.140348 }, stopover: false }, // R2M19
      { location: { lat: 22.253465, lng: 114.139154 }, stopover: false }, // R2M20
      { location: { lat: 22.253439, lng: 114.138809 }, stopover: false }, // R2M21
      { location: { lat: 22.256412, lng: 114.133759 }, stopover: false }, // R2M22
      { location: { lat: 22.261208, lng: 114.131094 }, stopover: false }, // R2M23
      { location: { lat: 22.262201, lng: 114.131131 }, stopover: false }, // R2M24
    ],
  },
}

// 工具函数：根据版本字符串返回当前激活的坐标/途径点
function getLocationMap(ver)    { return ver === 'new' ? _LOCATION_MAP_NEW    : _LOCATION_MAP_OLD }
function getRouteWaypoints(ver) { return ver === 'new' ? _ROUTE_WAYPOINTS_NEW : _ROUTE_WAYPOINTS_OLD }

export default function App() {
  const { isLoaded, loadError } = useJsApiLoader({
    id:              'google-map-script',
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY || '',
    libraries:        MAPS_LIBRARIES,
  })

  // ── 工作流状态 ──────────────────────────────────────────────────
  const [step, setStep]           = useState('select_origin')
  // 'select_origin' | 'view_routes' | 'select_time' | 'navigating'

  const [origin, setOrigin]       = useState(null)  // 'cyberport' | 'ma_on_shan'
  const [mode, setMode]           = useState(null)   // 'fast' | 'emotion'
  const [selectedRouteKey, setSelectedRouteKey] = useState(null)

  // ── 路线数据 ────────────────────────────────────────────────────
  const [fastRoute,     setFastRoute]     = useState(null)
  const [emotionRoute1, setEmotionRoute1] = useState(null)
  const [emotionRoute2, setEmotionRoute2] = useState(null)

  // ── 情感路线计算结果 ────────────────────────────────────────────
  const [bestEmotionRoute, setBestEmotionRoute] = useState(null)  // 1 | 2
  const [emotionResult,    setEmotionResult]    = useState(null)
  const [calculating,      setCalculating]      = useState(false)

  // ── 测试模式 & 路线版本 ─────────────────────────────────────────
  const [testMode,      setTestMode]      = useState(false)
  const [testModeRoute, setTestModeRoute] = useState(null)
  const [routeVersion,  setRouteVersion]  = useState('new')  // 从 API 动态获取

  // ── 定位（传入当前版本的坐标表，无需 rebuild 即可切换）─────────
  const { location, loading: locLoading, error: locError, locate, isAtOrigin } = useGeolocation(
    500, getLocationMap(routeVersion)
  )
  const [atOrigin, setAtOrigin] = useState(false)

  const mapRef = useRef(null)

  // ── 初始化：从 API 获取测试模式 & 路线版本 ──────────────────────
  useEffect(() => {
    getTestModeConfig()
      .then((cfg) => {
        setTestMode(cfg.test_mode)
        setTestModeRoute(cfg.forced_route)
        if (cfg.route_version) setRouteVersion(cfg.route_version)
      })
      .catch(() => {})
  }, [])

  // ── 定位后更新 atOrigin ────────────────────────────────────────
  useEffect(() => {
    if (location && origin) {
      setAtOrigin(isAtOrigin(origin))
    }
  }, [location, origin, isAtOrigin])

  // ── 请求路线（在地图加载且起点选择后，可传入指定出发时间） ──────
  const fetchAllRoutes = useCallback((originKey, departureTime = null) => {
    if (!window.google) return

    const locationMap     = getLocationMap(routeVersion)
    const routeWaypoints  = getRouteWaypoints(routeVersion)
    const origin  = locationMap[originKey]
    const dest    = originKey === 'cyberport' ? locationMap.ma_on_shan : locationMap.cyberport
    const ds      = new window.google.maps.DirectionsService()
    const depTime = departureTime ? new Date(departureTime) : new Date()

    const drivingOpts = {
      departureTime: depTime,
      trafficModel:  window.google.maps.TrafficModel.BEST_GUESS,
    }

    // Fast 路线（Google 自动最优）
    ds.route({
      origin,
      destination:    dest,
      travelMode:     window.google.maps.TravelMode.DRIVING,
      drivingOptions: drivingOpts,
    }, (result, status) => {
      if (status === 'OK') setFastRoute(result)
    })

    // 情感路线 1（路径固定，与最快路线使用同一交通模型）
    ds.route({
      origin,
      destination:    dest,
      travelMode:     window.google.maps.TravelMode.DRIVING,
      waypoints:      routeWaypoints.emotion1[originKey],
      drivingOptions: drivingOpts,
    }, (result, status) => {
      if (status === 'OK') {
        setEmotionRoute1(result)
      } else {
        console.error('[情感路线1] DirectionsService 返回错误:', status)
      }
    })

    // 情感路线 2（路径固定，与最快路线使用同一交通模型）
    ds.route({
      origin,
      destination:    dest,
      travelMode:     window.google.maps.TravelMode.DRIVING,
      waypoints:      routeWaypoints.emotion2[originKey],
      drivingOptions: drivingOpts,
    }, (result, status) => {
      if (status === 'OK') {
        setEmotionRoute2(result)
      } else {
        console.error('[情感路线2] DirectionsService 返回错误:', status)
      }
    })
  }, [routeVersion])

  // ── 回调：选择起点 ──────────────────────────────────────────────
  const handleSelectOrigin = useCallback((key) => {
    setOrigin(key)
    setFastRoute(null)
    setEmotionRoute1(null)
    setEmotionRoute2(null)
    setSelectedRouteKey(null)
    setBestEmotionRoute(null)
    setEmotionResult(null)
    setMode(null)
    setAtOrigin(false)
  }, [])

  // ── 回调：确认起点，进入路线视图并加载路线 ──────────────────────
  const handleConfirmStep = useCallback(() => {
    if (step === 'select_origin' && origin) {
      setStep('view_routes')
      if (isLoaded) fetchAllRoutes(origin)
    } else if (step === 'view_routes' && selectedRouteKey) {
      setStep('select_time')
    }
  }, [step, origin, selectedRouteKey, isLoaded, fetchAllRoutes])

  // ── 当地图加载完成时，如果起点已选，也触发路线加载 ─────────────
  useEffect(() => {
    if (isLoaded && step === 'view_routes' && origin) {
      fetchAllRoutes(origin)
    }
  }, [isLoaded]) // eslint-disable-line

  // ── 回调：选择模式 ──────────────────────────────────────────────
  const handleSelectMode = useCallback((m) => {
    setMode(m)
    setSelectedRouteKey(null)
    if (m === 'fast') {
      setSelectedRouteKey('fast')
    }
    setBestEmotionRoute(null)
    setEmotionResult(null)
  }, [])

  // ── 回调：手动选择路线卡片 ──────────────────────────────────────
  const handleSelectRoute = useCallback((key) => {
    setSelectedRouteKey(key)
  }, [])

  // ── 回调：获取交通数据 / 计算情感路线 ─────────────────────────────
  // 测试模式：调用 /get-traffic-data，获取真实 BTI，不推荐路线
  // 正式模式：调用 /calculate-emotion-route，获取 BTI + 推荐路线
  const handleCalculateEmotion = useCallback(async () => {
    if (!origin) return
    setCalculating(true)
    try {
      if (testMode) {
        const result = await getTrafficData(origin, null)
        // 保留 test_mode 标志供 ControlPanel 判断显示内容
        setEmotionResult({ ...result, test_mode: true })
        // 测试模式不自动推荐路线，用户手动选择
      } else {
        const result = await calculateEmotionRoute(origin, null)
        setEmotionResult(result)
        const recommended = result.recommended_route
        setBestEmotionRoute(recommended)
        setSelectedRouteKey(recommended === 1 ? 'emotion1' : 'emotion2')
      }
    } catch (err) {
      console.error('交通数据获取/计算失败:', err)
    } finally {
      setCalculating(false)
    }
  }, [origin, testMode])

  // ── 回调：定位 ──────────────────────────────────────────────────
  const handleLocate = useCallback(() => {
    locate()
  }, [locate])

  // ── 保存提示状态（导航开始时短暂显示） ────────────────────────────
  const [saveStatus, setSaveStatus] = useState(null)  // null | 'saving' | 'ok' | 'error'

  // ── 回调：开始导航（保存路线选择后进入导航模式） ──────────────────
  const handleStartNavigation = useCallback(async (departureTime) => {
    setSaveStatus('saving')
    try {
      await saveRouteSelection({
        origin,
        route_type:         mode,
        selected_route:     selectedRouteKey,
        best_emotion_route: bestEmotionRoute ?? null,
      })
      setSaveStatus('ok')
    } catch (err) {
      console.warn('[路线选择] 数据保存失败（继续导航）:', err)
      setSaveStatus('error')
    }

    if (departureTime && origin) {
      fetchAllRoutes(origin, departureTime)
    }
    setStep('navigating')
  }, [origin, mode, selectedRouteKey, bestEmotionRoute, fetchAllRoutes])

  // ── 回调：返回上一步 ────────────────────────────────────────────
  const handleBack = useCallback(() => {
    if (step === 'view_routes') {
      // 返回第一步：清除路线数据和所有选择状态
      setStep('select_origin')
      setMode(null)
      setSelectedRouteKey(null)
      setBestEmotionRoute(null)
      setEmotionResult(null)
      setAtOrigin(false)
      setFastRoute(null)
      setEmotionRoute1(null)
      setEmotionRoute2(null)
    } else if (step === 'select_time') {
      // 返回第二步：重置模式与路线选择，让用户重新选择（路线数据无需重新加载）
      setStep('view_routes')
      setMode(null)
      setSelectedRouteKey(null)
      setBestEmotionRoute(null)
      setEmotionResult(null)
    }
  }, [step])

  // ── 回调：结束导航 ──────────────────────────────────────────────
  const handleEndNavigation = useCallback(() => {
    setStep('select_origin')
    setOrigin(null)
    setMode(null)
    setSelectedRouteKey(null)
    setFastRoute(null)
    setEmotionRoute1(null)
    setEmotionRoute2(null)
    setBestEmotionRoute(null)
    setEmotionResult(null)
    setAtOrigin(false)
  }, [])

  // ── 当前激活路线的 DirectionsResult ────────────────────────────
  const activeRouteResult =
    selectedRouteKey === 'fast'     ? fastRoute     :
    selectedRouteKey === 'emotion1' ? emotionRoute1 : emotionRoute2

  // ── 地图高亮路线：view_routes 阶段未完成计算时不高亮任何路线 ──
  // - 计算前（含快速/情感模式选择期间）：三条路线等权显示
  // - 情感路线计算完成后：高亮推荐路线
  // - select_time / navigating：高亮已选路线
  const mapHighlightRoute = (step === 'view_routes' && !bestEmotionRoute) ? null : selectedRouteKey

  if (loadError) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-slate-100">
        <div className="text-center p-8 bg-white rounded-2xl shadow-lg">
          <p className="text-red-500 font-semibold text-lg mb-2">地图加载失败</p>
          <p className="text-slate-500 text-sm">请检查 Google Maps API Key 配置</p>
        </div>
      </div>
    )
  }

  if (!isLoaded) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-slate-100">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-600 font-medium">正在加载地图...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full h-full relative">
      {/* 全屏地图 */}
      <MapView
        fastRoute={fastRoute}
        emotionRoute1={emotionRoute1}
        emotionRoute2={emotionRoute2}
        highlightRoute={mapHighlightRoute}
        navigationMode={step === 'navigating'}
        onMapLoad={(map) => { mapRef.current = map }}
      />

      {/* 控制面板（导航模式隐藏） */}
      {step !== 'navigating' && (
        <ControlPanel
          step={step}
          mode={mode}
          origin={origin}
          selectedRouteKey={selectedRouteKey}
          bestEmotionRoute={bestEmotionRoute}
          emotionResult={emotionResult}
          fastRoute={fastRoute}
          emotionRoute1={emotionRoute1}
          emotionRoute2={emotionRoute2}
          calculating={calculating}
          testMode={testMode}
          testModeRoute={testModeRoute}
          routeVersion={routeVersion}
          onSelectOrigin={handleSelectOrigin}
          onSelectMode={handleSelectMode}
          onSelectRoute={handleSelectRoute}
          onCalculateEmotion={handleCalculateEmotion}
          onConfirmNavigation={handleConfirmStep}
          onStartNavigation={handleStartNavigation}
          onBack={handleBack}
        />
      )}

      {/* 导航状态栏 */}
      {step === 'navigating' && (
        <NavigationBar
          activeRoute={selectedRouteKey}
          directionsResult={activeRouteResult}
          saveStatus={saveStatus}
          onEnd={handleEndNavigation}
        />
      )}
    </div>
  )
}
