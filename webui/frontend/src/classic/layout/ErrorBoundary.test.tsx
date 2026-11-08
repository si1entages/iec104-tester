import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, afterEach } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'

function Boom(): never {
  throw new Error('页面炸了')
}

describe('ErrorBoundary', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('子组件抛错时显示可恢复提示而不是白屏', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('界面渲染出错')).toBeInTheDocument()
    expect(screen.getByText('页面炸了')).toBeInTheDocument()
    // antd 按钮对两个汉字自动插空格 → accessible name 是 "重 试"
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
    expect(spy).toHaveBeenCalled()
  })

  it('点「重试」且子树恢复后回到正常渲染', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    let shouldThrow = true
    function Conditional(): string {
      if (shouldThrow) throw new Error('boom')
      return '已恢复'
    }
    render(
      <ErrorBoundary>
        <Conditional />
      </ErrorBoundary>,
    )
    expect(screen.getByText('界面渲染出错')).toBeInTheDocument()
    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(screen.getByText('已恢复')).toBeInTheDocument()
  })

  it('无异常时原样渲染子树', () => {
    render(
      <ErrorBoundary>
        <div>正常内容</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('正常内容')).toBeInTheDocument()
  })
})
