import { useState, useCallback } from 'react'

const ORIGINS = {
  cyberport:  { lat: 22.262357, lng: 114.130918 },  // R1P01
  ma_on_shan: { lat: 22.426784, lng: 114.228231 },  // R1P21
}

/** 两点间距离（米），Haversine 公式 */
function haversineDistance(a, b) {
  const R = 6371000
  const toRad = (d) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const sinDLat = Math.sin(dLat / 2)
  const sinDLng = Math.sin(dLng / 2)
  const c =
    sinDLat * sinDLat +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * sinDLng * sinDLng
  return 2 * R * Math.atan2(Math.sqrt(c), Math.sqrt(1 - c))
}

/**
 * 定位钩子：获取当前位置，判断是否到达起点
 * @param {number} radiusMeters - 判定半径（默认 500m）
 */
export function useGeolocation(radiusMeters = 500) {
  const [location, setLocation]   = useState(null)  // { lat, lng, accuracy }
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)

  const locate = useCallback(() => {
    if (!navigator.geolocation) {
      setError('浏览器不支持地理定位')
      return
    }
    setLoading(true)
    setError(null)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({
          lat:      pos.coords.latitude,
          lng:      pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        })
        setLoading(false)
      },
      (err) => {
        setError(`定位失败: ${err.message}`)
        setLoading(false)
      },
      { enableHighAccuracy: true, timeout: 10000 }
    )
  }, [])

  /**
   * 判断用户是否在指定起点附近
   * @param {'cyberport'|'ma_on_shan'} originKey
   */
  const isAtOrigin = useCallback(
    (originKey) => {
      if (!location) return false
      const origin = ORIGINS[originKey]
      if (!origin) return false
      return haversineDistance(location, origin) <= radiusMeters
    },
    [location, radiusMeters]
  )

  return { location, loading, error, locate, isAtOrigin }
}
