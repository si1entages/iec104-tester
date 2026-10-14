import '@testing-library/jest-dom/vitest'

/**
 * antd v5 的响应式组件依赖 `matchMedia` / `ResizeObserver`，jsdom 未实现；
 * 这里补最小桩，避免组件测试因环境缺失而失败。
 */
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  })
}

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (!('ResizeObserver' in globalThis)) {
  Object.defineProperty(globalThis, 'ResizeObserver', {
    writable: true,
    value: ResizeObserverStub,
  })
}

/**
 * jsdom 未实现伪元素查询，rc-table 测量滚动条宽度时会打印
 * "Not implemented: window.getComputedStyle(elt, pseudoElt)" 噪声；
 * 忽略第二参数即可，行为对断言无影响。
 */
const nativeGetComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = ((element: Element) =>
  nativeGetComputedStyle(element)) as typeof window.getComputedStyle
