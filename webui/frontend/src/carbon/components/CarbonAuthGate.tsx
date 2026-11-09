import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { Button, TextInput, Tile } from '@carbon/react'

import { TOKEN_KEY, getToken } from '../../api/client'
import { api } from '../../api/endpoints'
import { useT } from '../../i18n'

type GateState = 'checking' | 'ok' | 'needed' | 'error'

/** 访问令牌闸门（B7）：服务端以 --auth-token 启动时，先校验令牌再渲染界面。 */
export function CarbonAuthGate({ children }: { children: ReactNode }) {
  const t = useT()
  const [state, setState] = useState<GateState>('checking')
  const [value, setValue] = useState('')

  useEffect(() => {
    try {
      const url = new URL(window.location.href)
      const fromUrl = url.searchParams.get('token')
      if (fromUrl) {
        localStorage.setItem(TOKEN_KEY, fromUrl)
        url.searchParams.delete('token')
        window.history.replaceState(null, '', url.pathname + url.search + url.hash)
      }
    } catch {
      // localStorage/URL 不可用时按无令牌处理
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
      <div style={{ padding: 64, textAlign: 'center', color: 'var(--cds-text-secondary)' }}>{t('auth.checking')}</div>
    )
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 96 }}>
      <Tile style={{ width: 460 }}>
        <h3 className="app-panel-title" style={{ marginBottom: 12 }}>
          {t('auth.title')}
        </h3>
        <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--cds-text-secondary)' }}>
          {state === 'error'
            ? t('auth.errorDesc')
            : `${t('auth.desc')} /app/?token=<token> ${t('auth.descSuffix')}`}
        </div>
        <TextInput
          id="carbon-auth-token"
          type="password"
          labelText={t('auth.placeholder')}
          placeholder={t('auth.placeholder')}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
            if (event.key === 'Enter') submit()
          }}
        />
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <Button kind="primary" disabled={!value.trim()} onClick={submit}>
            {t('auth.enter')}
          </Button>
          {state === 'error' ? (
            <Button kind="secondary" onClick={() => window.location.reload()}>
              {t('auth.retry')}
            </Button>
          ) : null}
        </div>
      </Tile>
    </div>
  )
}
