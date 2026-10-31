import { ElMessageBox } from 'element-plus'
import type { Ref } from 'vue'

/**
 * 弹层的「有未保存改动就不让随手关」拦截（第四十七轮）。
 *
 * 三条关闭路径——点遮罩、点 ✕、按 Esc——`el-dialog` / `el-drawer` 都会先过
 * `before-close`，所以拦这一处就够，不用逐个去改 v-model 的赋值点。
 *
 * ## 为什么不能用 `watch(visible)` 拦
 *
 * 确认后要**真的关掉**，只能把 v-model 置 false；而 `watch(visible)` 拦的正是
 * 这次置 false —— 拦住自己要放行的那次，就是死循环。`before-close` 天然没这个问题：
 * 确认后直接 `visible.value = false`，不再走 `before-close`。
 *
 * ## `dirty` 由调用方给
 *
 * 三个弹层的「改了没存」判据各不相同（草稿表、表单对象、答案 ref），
 * 这里只认一个布尔：要么传 `ComputedRef<boolean>`，要么传 `Ref<boolean>`。
 * 判据留在各组件里，漂不了。
 */
export function useCloseGuard(
  visible: Ref<boolean>,
  dirty: Ref<boolean> | { value: boolean },
  /** 自定义确认文案。不传就用默认那句（够用，但带上「几个人」会更清楚） */
  message?: () => string,
) {
  /**
   * 给 `el-dialog` / `el-drawer` 的 `:before-close`。
   *
   * 没有未保存改动就直接关；有的话弹确认。用户选「继续填写」则什么都不做，
   * 弹层保持打开（`before-close` 不调 `done()`、也不改 v-model，就不会关）。
   */
  function onBeforeClose() {
    if (!dirty.value) {
      visible.value = false
      return
    }
    ElMessageBox.confirm(
      message?.() ?? '还有未保存的内容，关闭会丢掉这些改动。确定关闭？',
      '关闭',
      { type: 'warning', confirmButtonText: '直接关闭', cancelButtonText: '继续填写' },
    )
      .then(() => {
        visible.value = false
      })
      .catch(() => {
        /* 继续填写：保持打开 */
      })
  }

  return { onBeforeClose }
}
