import React, { useRef, useEffect, useCallback } from 'react'
import { GoogleMap } from '@react-google-maps/api'

const containerStyle = { width: '100%', height: '100%' }
const HK_CENTER = { lat: 22.34, lng: 114.19 }

// ── 路线样式配置 ─────────────────────────────────────────────────────
const ROUTE_STYLES = {
  fast: {
    main:          '#2563EB',   // 蓝色
    glowInner:     '#60A5FA',
    glowOuter:     '#BFDBFE',
    label:         '⚡ Fast',
    direction:     'upper-left',
    labelFraction: 0.5,         // 取路线中点
    mainWeight:    7,
    zIndex:        9,
  },
  emotion1: {
    main:          '#059669',   // 绿色
    glowInner:     '#34D399',
    glowOuter:     '#A7F3D0',
    label:         '♥ Experience ①',
    direction:     'upper-left',
    labelFraction: 0.35,        // 取路线前段（与 emotion2 错开）
    mainWeight:    6,
    zIndex:        10,
  },
  emotion2: {
    main:          '#D97706',   // 琥珀
    glowInner:     '#FBBF24',
    glowOuter:     '#FDE68A',
    label:         '♥ Experience ②',
    direction:     'lower-right',
    labelFraction: 0.78,        // 取路线后段（与 emotion1 错开）
    mainWeight:    5,
    zIndex:        11,
  },
}

const MAP_STYLES = [
  { featureType: 'poi',     elementType: 'labels', stylers: [{ visibility: 'off' }] },
  { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] },
]

// ── 标签 SVG（引导线式）───────────────────────────────────────────────
/**
 * direction = 'upper-left' : pill 在左上，锚点在右下 → 标签偏离路线左上方
 * direction = 'lower-right': pill 在右下，锚点在左上 → 标签偏离路线右下方
 */
function makeLabelIcon(text, color, isSelected, dimmed, direction = 'upper-left') {
  const paddingX   = 18
  const pillH      = 42
  const fontSize   = 15
  const leaderOffX = 38
  const leaderOffY = 32

  const charWidth = [...text].reduce((acc, ch) => {
    if (/[\u4e00-\u9fff]/.test(ch)) return acc + 16
    if (/[^\x00-\x7F]/.test(ch))    return acc + 14   // emoji / 圆圈数字
    return acc + 9
  }, 0)
  const pillW  = Math.ceil(charWidth + paddingX * 2)
  const totalW = pillW + leaderOffX + 8
  const totalH = pillH + leaderOffY + 8

  const bgFill   = isSelected ? color : '#FFFFFF'
  const textFill = isSelected ? '#FFFFFF' : color
  const opacity  = dimmed ? 0.38 : 1
  const pillFilter = isSelected
    ? `drop-shadow(0 0 5px ${color}) drop-shadow(0 0 14px ${color})`
    : 'drop-shadow(0 2px 6px rgba(0,0,0,0.24))'

  // 根据方向计算 pill / 锚点 / 引导线坐标
  let anchorX, anchorY, pillX, pillY, lx1, ly1, lx2, ly2

  if (direction === 'upper-left') {
    // pill 位于左上角，锚点位于右下角
    anchorX = totalW - 4
    anchorY = totalH - 4
    pillX   = 0;  pillY = 0
    lx1 = pillW + 1;       ly1 = pillH / 2   // 引导线从 pill 右侧中心出发
    lx2 = anchorX;         ly2 = anchorY
  } else {
    // pill 位于右下角，锚点位于左上角
    anchorX = 4;  anchorY = 4
    pillX   = leaderOffX;  pillY = leaderOffY
    lx1 = anchorX;                ly1 = anchorY    // 引导线从锚点出发
    lx2 = leaderOffX - 1;         ly2 = leaderOffY + pillH / 2  // 到 pill 左侧中心
  }

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${totalW}" height="${totalH}" opacity="${opacity}">
      <line x1="${lx1}" y1="${ly1}" x2="${lx2}" y2="${ly2}"
            stroke="${color}" stroke-width="2.5" stroke-linecap="round" opacity="0.88"/>
      <circle cx="${anchorX}" cy="${anchorY}" r="6"  fill="${color}" opacity="0.92"/>
      <circle cx="${anchorX}" cy="${anchorY}" r="3"  fill="white"/>
      <rect x="${pillX + 1.5}" y="${pillY + 1.5}" width="${pillW - 3}" height="${pillH - 3}"
            rx="16" ry="16" fill="${bgFill}" stroke="${color}" stroke-width="2.5"
            filter="${pillFilter}"/>
      <text x="${pillX + pillW / 2}" y="${pillY + pillH / 2}"
            text-anchor="middle" dominant-baseline="central"
            font-family="Inter,-apple-system,BlinkMacSystemFont,sans-serif"
            font-size="${fontSize}" font-weight="700" fill="${textFill}">${text}</text>
    </svg>`

  return {
    url:        'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg),
    scaledSize: new window.google.maps.Size(totalW, totalH),
    anchor:     new window.google.maps.Point(anchorX, anchorY),
  }
}

function getRouteMidpoint(result, fraction = 0.5) {
  const path = result?.routes?.[0]?.overview_path
  if (!path?.length) return null
  return path[Math.floor(path.length * fraction)]
}

function getRoutePath(result) {
  return result?.routes?.[0]?.overview_path || []
}

// ── 主组件 ───────────────────────────────────────────────────────────
export default function MapView({
  fastRoute, emotionRoute1, emotionRoute2,
  highlightRoute, navigationMode, onMapLoad,
}) {
  const mapRef          = useRef(null)
  const renderersRef    = useRef({ fast: null, emotion1: null, emotion2: null })
  const borderLinesRef  = useRef({ fast: null, emotion1: null, emotion2: null })
  const glowLayersRef   = useRef({ fast: [], emotion1: [], emotion2: [] })
  const labelMarkersRef = useRef({ fast: null, emotion1: null, emotion2: null })

  // ── 白色描边：让重叠路线有视觉分隔 ──────────────────────────────
  const createBorderLine = useCallback((key, path) => {
    if (!mapRef.current || !path?.length) return
    if (borderLinesRef.current[key]) borderLinesRef.current[key].setMap(null)
    borderLinesRef.current[key] = new window.google.maps.Polyline({
      path,
      strokeColor:   'white',
      strokeWeight:  ROUTE_STYLES[key].mainWeight + 4,
      strokeOpacity: 0.72,
      zIndex:        ROUTE_STYLES[key].zIndex - 2,  // 描边低于主线
      map:           mapRef.current,
      clickable:     false,
    })
  }, [])

  // ── 荧光光晕层（选中时） ──────────────────────────────────────────
  const clearGlowLayers = useCallback((key) => {
    glowLayersRef.current[key].forEach((p) => p.setMap(null))
    glowLayersRef.current[key] = []
  }, [])

  // zIndexBase 默认用路线自身层级；选中时传入 98 使光晕层浮至最顶
  const createGlowLayers = useCallback((key, path, zIndexBase) => {
    if (!mapRef.current || !path?.length) return
    clearGlowLayers(key)
    const s    = ROUTE_STYLES[key]
    const base = zIndexBase ?? s.zIndex
    const layers = [
      { color: s.glowOuter, weight: 22, opacity: 0.28, zIndex: base - 1 },
      { color: s.glowInner, weight: 14, opacity: 0.55, zIndex: base     },
      { color: s.glowInner, weight:  8, opacity: 0.85, zIndex: base + 1 },
    ]
    glowLayersRef.current[key] = layers.map(({ color, weight, opacity, zIndex }) =>
      new window.google.maps.Polyline({
        path, strokeColor: color, strokeWeight: weight,
        strokeOpacity: opacity, zIndex, map: mapRef.current, clickable: false,
      })
    )
  }, [clearGlowLayers])

  // ── 创建 / 更新标签 Marker ────────────────────────────────────────
  const upsertLabelMarker = useCallback((key, result, isSelected, dimmed) => {
    const s       = ROUTE_STYLES[key]
    const midpoint = getRouteMidpoint(result, s.labelFraction ?? 0.5)
    if (!midpoint || !mapRef.current) return
    const icon = makeLabelIcon(s.label, s.main, isSelected, dimmed, s.direction)
    if (labelMarkersRef.current[key]) {
      labelMarkersRef.current[key].setPosition(midpoint)
      labelMarkersRef.current[key].setIcon(icon)
      labelMarkersRef.current[key].setZIndex(isSelected ? 50 : 30)
    } else {
      labelMarkersRef.current[key] = new window.google.maps.Marker({
        position: midpoint, map: mapRef.current,
        icon, clickable: false, zIndex: isSelected ? 50 : 30,
      })
    }
  }, [])

  // ── 初始化 DirectionsRenderer ─────────────────────────────────────
  const initRenderer = useCallback((key) => {
    if (renderersRef.current[key]) renderersRef.current[key].setMap(null)
    const s = ROUTE_STYLES[key]
    renderersRef.current[key] = new window.google.maps.DirectionsRenderer({
      suppressMarkers: false, preserveViewport: true,
      polylineOptions: {
        strokeColor:   s.main,
        strokeWeight:  s.mainWeight,
        strokeOpacity: 1,
        zIndex:        s.zIndex + 2,  // 主线在描边 + 光晕之上
      },
    })
  }, [])

  const onLoad = useCallback((map) => {
    mapRef.current = map
    initRenderer('fast'); initRenderer('emotion1'); initRenderer('emotion2')
    if (onMapLoad) onMapLoad(map)
  }, [initRenderer, onMapLoad])

  // ── 路线数据变化：挂载渲染器 + 描边 + 标签 ───────────────────────
  useEffect(() => {
    const routeMap = { fast: fastRoute, emotion1: emotionRoute1, emotion2: emotionRoute2 }
    Object.entries(routeMap).forEach(([key, result]) => {
      const renderer = renderersRef.current[key]
      if (!renderer) return
      if (result) {
        renderer.setMap(mapRef.current)
        renderer.setDirections(result)
        createBorderLine(key, getRoutePath(result))
        const isSelected = highlightRoute === key
        const dimmed     = highlightRoute !== null && !isSelected
        upsertLabelMarker(key, result, isSelected, dimmed)
      } else {
        renderer.setMap(null)
        clearGlowLayers(key)   // 路线清除时同步移除光晕层
        if (borderLinesRef.current[key]) borderLinesRef.current[key].setMap(null)
        if (labelMarkersRef.current[key]) {
          labelMarkersRef.current[key].setMap(null)
          labelMarkersRef.current[key] = null
        }
      }
    })
  }, [fastRoute, emotionRoute1, emotionRoute2, clearGlowLayers]) // eslint-disable-line

  // ── 高亮状态变化 ─────────────────────────────────────────────────
  useEffect(() => {
    const routeMap  = { fast: fastRoute, emotion1: emotionRoute1, emotion2: emotionRoute2 }
    const hasHigh   = highlightRoute !== null

    Object.entries(renderersRef.current).forEach(([key, renderer]) => {
      if (!renderer) return
      const result     = routeMap[key]
      const isSelected = highlightRoute === key
      const dimmed     = hasHigh && !isSelected
      const s          = ROUTE_STYLES[key]

      // ── 导航模式 ──────────────────────────────────────────────
      if (navigationMode) {
        if (isSelected && result) {
          renderer.setMap(mapRef.current)
          renderer.setOptions({ polylineOptions: {
            strokeColor: s.main, strokeWeight: s.mainWeight + 2,
            strokeOpacity: 1, zIndex: 102,   // 选中路线永远最顶层
          }})
          createGlowLayers(key, getRoutePath(result), 98)
          upsertLabelMarker(key, result, true, false)
          if (borderLinesRef.current[key]) {
            borderLinesRef.current[key].setOptions({ zIndex: 96 })
            borderLinesRef.current[key].setMap(mapRef.current)
          }
        } else {
          renderer.setMap(null)
          clearGlowLayers(key)
          if (borderLinesRef.current[key]) borderLinesRef.current[key].setMap(null)
          if (labelMarkersRef.current[key]) labelMarkersRef.current[key].setMap(null)
        }
        return
      }

      // ── 普通模式 ──────────────────────────────────────────────
      if (isSelected) {
        renderer.setOptions({ polylineOptions: {
          strokeColor: s.main, strokeWeight: s.mainWeight + 2,
          strokeOpacity: 1, zIndex: 102,     // 选中路线永远最顶层
        }})
        createGlowLayers(key, getRoutePath(result), 98)
        if (borderLinesRef.current[key]) {
          borderLinesRef.current[key].setOptions({ zIndex: 96 })
          borderLinesRef.current[key].setMap(mapRef.current)
        }
      } else {
        clearGlowLayers(key)
        renderer.setOptions({ polylineOptions: {
          strokeColor:   s.main,
          strokeWeight:  s.mainWeight,
          strokeOpacity: dimmed ? 0.45 : 1,
          zIndex:        dimmed ? 4 : s.zIndex + 2,
        }})
        if (borderLinesRef.current[key]) {
          borderLinesRef.current[key].setOptions({ strokeOpacity: dimmed ? 0.35 : 0.72 })
          // 仅当路线数据存在时才把描边放回地图，防止路线已清除后描边残留
          if (result) borderLinesRef.current[key].setMap(mapRef.current)
        }
      }

      if (result) upsertLabelMarker(key, result, isSelected, dimmed)
    })
  }, [highlightRoute, navigationMode, fastRoute, emotionRoute1, emotionRoute2,
      createGlowLayers, clearGlowLayers, upsertLabelMarker, createBorderLine])

  // ── 自适应视野 ────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return
    const results = [fastRoute, emotionRoute1, emotionRoute2].filter(Boolean)
    if (results.length === 0) return
    const bounds = new window.google.maps.LatLngBounds()
    results.forEach((r) =>
      r.routes[0].legs.forEach((leg) =>
        leg.steps.forEach((step) => {
          bounds.extend(step.start_location)
          bounds.extend(step.end_location)
        })
      )
    )
    mapRef.current.fitBounds(bounds, { top: 60, right: 60, bottom: 60, left: 420 })
  }, [fastRoute, emotionRoute1, emotionRoute2])

  return (
    <GoogleMap
      mapContainerStyle={containerStyle}
      center={HK_CENTER}
      zoom={11}
      onLoad={onLoad}
      options={{
        styles:            MAP_STYLES,
        disableDefaultUI:  false,
        zoomControl:       true,
        mapTypeControl:    false,
        streetViewControl: false,
        fullscreenControl: false,
      }}
    />
  )
}
