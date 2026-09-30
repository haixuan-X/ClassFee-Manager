import { onUnmounted, watch, type Ref } from 'vue'

/**
 * 弹窗（dialog/drawer）通用行为，两件事：
 *
 * 1. **Esc 关闭兜底**：Element Plus 的 el-select 对 Escape 一律
 *    preventDefault + stopPropagation，焦点停在选择框上时弹窗自带的
 *    Esc 收不到事件 → 这里在捕获阶段兜底；若下拉 / 日期面板正展开，
 *    则让组件先关面板（本次不关弹窗）。
 * 2. **焦点还原**：记录打开时的触发元素，`@closed="restoreFocus"` 还回去，
 *    键盘用户关闭后不会被丢回页面顶部。
 *
 * 面板是否展开用 .el-popper 的实际 display 判断（EP 弹层不打开也挂在 DOM 上）。
 *
 * 嵌套弹层（抽屉上的对话框、弹窗上的确认框）只有**最上层**能消费 Esc：
 * 传入 `root`（弹层内的元素或带 $el 的组件）时按 z-index 判定层级；
 * 没传 root 则保守地只在“唯一可见弹层”时关闭，避免一次 Esc 关掉两层。
 */
export function useModal(visible: Ref<boolean>, root?: Ref<unknown>) {
  let opener: HTMLElement | null = null

  function restoreFocus() {
    const usable = (el: HTMLElement | null): el is HTMLElement =>
      !!el && el.isConnected && el.getClientRects().length > 0
    if (usable(opener)) opener.focus()
  }

  function resolveEl(value: unknown): HTMLElement | null {
    if (value instanceof HTMLElement) return value
    const el = (value as { $el?: unknown } | null)?.$el
    return el instanceof HTMLElement ? el : null
  }

  /** 本弹层是否是当前最上层可见弹层（能消费 Esc） */
  function isTopOverlay(): boolean {
    const overlays = [...document.querySelectorAll('.el-overlay')].filter(
      (el) => getComputedStyle(el).display !== 'none',
    )
    if (overlays.length <= 1) return true
    const mine = resolveEl(root?.value)?.closest('.el-overlay')
    if (!mine) return false
    const myZ = Number(getComputedStyle(mine).zIndex) || 0
    return overlays.every((el) => (Number(getComputedStyle(el).zIndex) || 0) <= myZ)
  }

  function onGlobalKeydown(e: KeyboardEvent) {
    if (e.key !== 'Escape' || !visible.value) return
    const panelOpen = [...document.querySelectorAll('.el-popper')].some(
      (el) => getComputedStyle(el).display !== 'none',
    )
    if (panelOpen) return
    if (!isTopOverlay()) return
    visible.value = false
  }

  watch(visible, (open) => {
    if (open) {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.addEventListener('keydown', onGlobalKeydown, true)
    } else {
      document.removeEventListener('keydown', onGlobalKeydown, true)
    }
  })

  onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown, true))

  return { restoreFocus }
}
