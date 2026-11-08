import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { Alert, Button } from '@patternfly/react-core'

import { tNow } from '../../i18n'

interface Props {
  children: ReactNode
  /** 页面键：切换页面时重置错误状态 */
  resetKey?: string
}

interface State {
  error: Error | null
}

/** 页面级错误边界：单页抛错只影响本页，外壳与其它页面不受牵连。 */
export class PfErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 保留控制台可见性，便于现场排查
    console.error('page render failed', error, info.componentStack)
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    return (
      <Alert
        isInline
        variant="danger"
        title={tNow('common.loadFailed')}
        actionLinks={
          <Button variant="link" onClick={() => window.location.reload()}>
            {tNow('common.retry')}
          </Button>
        }
      >
        {this.state.error.message}
      </Alert>
    )
  }
}
