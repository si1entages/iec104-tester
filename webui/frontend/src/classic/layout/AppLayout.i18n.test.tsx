import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useUiStore } from '../store/uiStore'
import { AppLayout } from './AppLayout'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function setup(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      if (String(input).startsWith('/api/status')) {
        return jsonResponse({ role: 'master', running: false, schemaVersion: 1 })
      }
      return jsonResponse({ ok: true })
    }),
  )
  render(
    <QueryClientProvider client={client}>
      <AppLayout>
        <div>content</div>
      </AppLayout>
    </QueryClientProvider>,
  )
}

describe('AppLayout i18n（C3：英文界面）', () => {
  beforeEach(() => {
    localStorage.setItem('iec104_locale', 'en')
    useUiStore.setState({ locale: 'en' })
  })

  afterEach(() => {
    localStorage.removeItem('iec104_locale')
    useUiStore.setState({ locale: 'zh' })
    vi.unstubAllGlobals()
  })

  it('locale=en 时导航与头部为英文', async () => {
    setup()
    await waitFor(() =>
      expect(
        screen.getByRole('menuitem', { name: /Master Workbench/ }),
      ).toBeInTheDocument(),
    )
    for (const name of [/Multi-Station/, /Status/, /Logs/, /History/]) {
      expect(screen.getByRole('menuitem', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Dark mode' })).toBeInTheDocument()
  })
})
