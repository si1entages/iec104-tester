import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { Button, Result, Typography } from 'antd'

import { tNow } from '../i18n'

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
        title={tNow('error.title')}
        subTitle={error.message}
        extra={
          <Button type="primary" onClick={this.handleReset}>
            {tNow('error.retry')}
          </Button>
        }
      >
        <Typography.Paragraph type="secondary">
          {tNow('error.hint')}
        </Typography.Paragraph>
      </Result>
    )
  }
}
