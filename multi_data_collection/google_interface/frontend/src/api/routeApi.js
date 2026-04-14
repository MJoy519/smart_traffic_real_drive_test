import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE_URL || '/api'

const api = axios.create({ baseURL: BASE, timeout: 30000 })

/**
 * 计算最优情感路线
 * @param {string} originKey - 'cyberport' | 'ma_on_shan'
 * @param {string|null} departureTime - ISO 时间字符串，null 表示当前时间
 * @returns {Promise<{recommended_route:number, reason:string, ...}>}
 */
export async function calculateEmotionRoute(originKey, departureTime = null) {
  const { data } = await api.post('/calculate-emotion-route', {
    origin_key:     originKey,
    departure_time: departureTime,
  })
  return data
}

/**
 * 获取情感路线固定数据（经纬度 + 分段）
 * @param {1|2} routeId
 */
export async function getRouteData(routeId) {
  const { data } = await api.get(`/route-data/${routeId}`)
  return data
}

/**
 * 获取测试模式配置
 */
export async function getTestModeConfig() {
  const { data } = await api.get('/config/test-mode')
  return data
}

/**
 * 保存路线选择记录到受试者文件夹
 * @param {{
 *   origin: string,
 *   route_type: string,
 *   selected_route: string,
 *   best_emotion_route: number|null
 * }} selectionData
 */
export async function saveRouteSelection(selectionData) {
  const { data } = await api.post('/save-route', selectionData)
  return data
}
