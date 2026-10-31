/**
 * 图表 resize 的防抖包装。
 *
 * ## 为什么需要它
 *
 * 三个图表组件（趋势图 / 饼图 / 学籍趋势）各自挂一个 `window.resize` 监听。
 * 浏览器的 resize 事件在**拖动窗口时每帧都触发**（≈60 次/秒），
 * 没有防抖的话，拖一下窗口 = 每帧都调 `chart.resize()` ——
 * 而 `resize()` 会重新量容器尺寸并**整块重画**图表（含动画）。
 *
 * 这笔成本在自动化环境里是**看不见的**：rAF 被节流成 0 帧，
 * 页面根本没在绘制，量出来 CPU 一直是绿的；但在真实浏览器里
 * 拖窗口会明显掉帧，低端机直接卡住。
 *
 * ## 为什么用 rAF 而不是 setTimeout
 *
 * `requestAnimationFrame` 把重画**对齐到下一帧的绘制时机**：
 * 一帧内拖多少次都只画一次，且不会在页面不可见时白跑。
 * `setTimeout(fn, 150)` 做不到这两点——不可见时照样跑，还可能
 * 跑在两帧之间导致多画一次。
 *
 * ## 没有 cancel 的泄漏风险吗
 *
 * 没有。回调只读取组件内的 `chart` 引用（组件卸载时已 dispose 并置 null），
 * 组件卸载时会 `removeEventListener`，之后这个函数不会再被调用。
 */
export function rafThrottle<T extends (...args: never[]) => void>(fn: T): T {
  let frame = 0
  const wrapped = (...args: Parameters<T>) => {
    if (frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      fn(...args)
    })
  }
  return wrapped as T
}
