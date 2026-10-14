import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { Button, Result, Typography } from 'antd'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** 全局错误边界：任何渲染期异常都不至于白屏。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[ui] uncaught error', error, info)
  }

  private handleReset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <Result
        status="error"
        title="界面渲染出错"
        subTitle={error.message}
        extra={
          <Button type="primary" onClick={this.handleReset}>
            重试
          </Button>
        }
      >
        <Typography.Paragraph type="secondary">
          可先尝试重试或刷新页面；若持续复现，请在后端控制台查看日志。
        </Typography.Paragraph>
      </Result>
    )
  }
}
