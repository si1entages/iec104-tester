import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { Button, Card, Input, Space, Spin, Typography } from 'antd'

import { TOKEN_KEY, getToken } from '../api/client'
import { api } from '../api/endpoints'
import { useT } from '../i18n'

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
  const t = useT()
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
        <Spin description={t('auth.checking')} size="large">
          <div style={{ width: 200, height: 60 }} />
        </Spin>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 96 }}>
      <Card title={t('auth.title')} style={{ width: 440 }}>
        <Typography.Paragraph type="secondary">
          {state === 'error' ? t('auth.errorDesc') : t('auth.desc')}
          {state === 'error' ? null : (
            <Typography.Text code>/app/?token=&lt;token&gt;</Typography.Text>
          )}
          {state === 'error' ? null : ` ${t('auth.descSuffix')}`}
        </Typography.Paragraph>
        <Space.Compact style={{ width: '100%' }}>
          <Input.Password
            placeholder={t('auth.placeholder')}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onPressEnter={submit}
          />
          <Button type="primary" onClick={submit} disabled={!value.trim()}>
            {t('auth.enter')}
          </Button>
        </Space.Compact>
        {state === 'error' ? (
          <Button style={{ marginTop: 12 }} onClick={() => window.location.reload()}>
            {t('auth.retry')}
          </Button>
        ) : null}
      </Card>
    </div>
  )
}
