import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

declare module 'axios' {
  interface AxiosRequestConfig {
    skipErrorToast?: boolean
  }
}

export class ApiError extends Error {
  code: string
  detail: Record<string, unknown>
  status?: number

  constructor(message: string, code = 'error', detail: Record<string, unknown> = {}, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
    this.status = status
  }
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 180_000,
  headers: { 'Content-Type': 'application/json' },
})

let lastToast = ''
let lastToastAt = 0

function toast(message: string) {
  const now = Date.now()
  if (message === lastToast && now - lastToastAt < 1500) return
  lastToast = message
  lastToastAt = now
  ElMessage.error({ message, duration: 5000, showClose: true })
}

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && body.success === false) {
      const error = body.error ?? {}
      const apiError = new ApiError(error.message || '请求失败', error.code, error.detail, response.status)
      if (!response.config.skipErrorToast) toast(apiError.message)
      return Promise.reject(apiError)
    }
    return body?.data
  },
  (error) => {
    const silent = Boolean(error.config?.skipErrorToast)
    if (error.response) {
      const body = error.response.data ?? {}
      const payload = body.error ?? {}
      const message =
        payload.message ||
        (typeof body.detail === 'string' ? body.detail : '') ||
        `请求失败（${error.response.status}）`
      const apiError = new ApiError(message, payload.code || 'http_error', payload.detail || {}, error.response.status)
      if (!silent) toast(message)
      return Promise.reject(apiError)
    }
    if (error.code === 'ECONNABORTED') {
      const apiError = new ApiError('请求超时，请检查后端服务或模型接口', 'timeout')
      if (!silent) toast(apiError.message)
      return Promise.reject(apiError)
    }
    const message = '无法连接后端服务，请确认 FastAPI 已启动（127.0.0.1:8000）'
    if (!silent) toast(message)
    return Promise.reject(new ApiError(message, 'network_error'))
  },
)

export function downloadUrl(url: string) {
  if (!url) return '#'
  return url.startsWith('http') ? url : url
}

export default http
