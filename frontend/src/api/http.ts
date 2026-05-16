import axios, { type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/store/auth'
import router from '@/router'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res.data,
  async (error) => {
    const status = error?.response?.status
    if (status === 401) {
      const auth = useAuthStore()
      auth.clear()
      router.push('/login')
    }
    const detail = error?.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    return Promise.reject(error)
  }
)

export function request<T = unknown>(config: AxiosRequestConfig): Promise<T> {
  return http.request<unknown, T>(config)
}

/**
 * 文件下载（CSV / XLSX 等）。
 * - 走独立 axios 实例避开 response 拦截器（保留 headers / blob 原貌）
 * - 自动从 Content-Disposition 解析 filename（兼容 RFC 5987 ``filename*=UTF-8''xxx``）
 * - 兜底文件名通过参数传入
 */
export async function download(
  config: AxiosRequestConfig,
  fallbackFilename: string,
): Promise<void> {
  const auth = useAuthStore()
  const res = await axios.request({
    baseURL: '/api/v1',
    timeout: 60000,
    responseType: 'blob',
    ...config,
    headers: {
      ...(config.headers || {}),
      ...(auth.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
    },
  })

  const cd: string = res.headers?.['content-disposition'] || ''
  let filename = fallbackFilename
  const star = /filename\*\s*=\s*([^;]+)/i.exec(cd)
  if (star) {
    const v = star[1].trim()
    const m = /^([^']*)'[^']*'(.+)$/.exec(v)
    try {
      filename = decodeURIComponent(m ? m[2] : v)
    } catch {
      filename = m ? m[2] : v
    }
  } else {
    const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(cd)
    if (plain) filename = plain[1]
  }

  const blob = new Blob([res.data], {
    type: res.headers?.['content-type'] || 'application/octet-stream',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('已开始下载：' + filename)
}

export default http
