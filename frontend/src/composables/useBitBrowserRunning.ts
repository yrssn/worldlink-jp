import { computed, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { bitbrowserApi, type BitBrowserRunningRow } from '@/api/bitbrowser'

/** 拉取本机运行中窗口（``GET /bitbrowser/running``，底层 ``POST /browser/pids/all``） */
export function useBitBrowserRunning(connReady: Ref<boolean>) {
  const runningList = ref<BitBrowserRunningRow[]>([])
  const runningLoading = ref(false)

  const runningPidMap = computed(() => {
    const m: Record<string, number> = {}
    for (const it of runningList.value) {
      m[it.browser_id] = it.pid
    }
    return m
  })

  const runningById = computed(() => {
    const m: Record<string, BitBrowserRunningRow> = {}
    for (const it of runningList.value) {
      m[it.browser_id] = it
    }
    return m
  })

  async function loadRunning() {
    if (!connReady.value) {
      runningList.value = []
      return
    }
    runningLoading.value = true
    try {
      const r = await bitbrowserApi.listRunning()
      runningList.value = r.items
    } catch {
      runningList.value = []
    } finally {
      runningLoading.value = false
    }
  }

  async function closeRunning(browserId: string) {
    try {
      await bitbrowserApi.closeWindow(browserId)
      ElMessage.success('已发送关闭请求')
    } catch {
      /* 拦截器已提示 */
    }
    await loadRunning()
  }

  return { runningList, runningLoading, runningPidMap, runningById, loadRunning, closeRunning }
}
