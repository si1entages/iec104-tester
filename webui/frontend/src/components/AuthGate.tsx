import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { Button, Card, Input, Space, Spin, Typography } from 'antd'

import { TOKEN_KEY, getToken } from '../api/client'
import { api } from '../api/endpoints'

type GateState = 'checking' | 'ok' | 'needed' | 'error'

/**
 * 访问令牌闸门（B7）。
 *
 * 服务端以 --auth-token 启动时，除 /api/auth 外的所有 API/WS 需要令牌：
 *  - URL `?token=...` 首次导入 localStorage 后从地址栏移除（便于局域网首次访问）；
 *  - 探测 /api/auth 决定是否需要展示令牌输入框；
 *  - 令牌无效/缺失时停留在输入框，不渲染主界面（避免满屏 401 报错）。
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>('checking')
  const [value, setValue] = useState('')

  useEffect(() => {
    // URL ?token= 一次性导入（随后从地址栏移除，避免日志/书签泄露）
    try {
      const url = new URL(window.location.href)
      const fromUrl = url.searchParams.get('token')
      if (fromUrl) {
        localStorage.setItem(TOKEN_KEY, fromUrl)
        url.searchParams.delete('token')
        window.history.replaceState(null, '', url.pathname + url.hash)
      }
    } catch {
      // localStorage/URL 不可用时继续按无令牌处理
    }

    const token = getToken()
    api
      .auth(token || undefined)
      .then((body) => {
        if (!body.required) setState('ok')
        else setState(body.valid ? 'ok' : 'needed')
      })
      .catch(() => setState('error'))
  }, [])

  const submit = (): void => {
    const token = value.trim()
    if (!token) return
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      // 忽略：刷新后仍会提示
    }
    window.location.reload()
  }

  if (state === 'ok') return <>{children}</>
  if (state === 'checking') {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 64 }}>
        <Spin tip="校验访问令牌…" size="large">
          <div style={{ width: 200, height: 60 }} />
        </Spin>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 96 }}>
      <Card title="需要访问令牌" style={{ width: 440 }}>
        <Typography.Paragraph type="secondary">
          {state === 'error'
            ? '无法连接后端（/api/auth 探测失败）。请确认服务已启动后重试。'
            : '服务端已启用 Web API 认证（--auth-token）。请输入访问令牌；也可直接访问 '}
          {state === 'error' ? null : (
            <Typography.Text code>/app/?token=&lt;token&gt;</Typography.Text>
          )}
          {state === 'error' ? null : ' 由服务端导入。'}
        </Typography.Paragraph>
        <Space.Compact style={{ width: '100%' }}>
          <Input.Password
            placeholder="访问令牌"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onPressEnter={submit}
          />
          <Button type="primary" onClick={submit} disabled={!value.trim()}>
            进入
          </Button>
        </Space.Compact>
        {state === 'error' ? (
          <Button style={{ marginTop: 12 }} onClick={() => window.location.reload()}>
            重试
          </Button>
        ) : null}
      </Card>
    </div>
  )
}
