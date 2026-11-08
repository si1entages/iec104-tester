import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MultiPage from './MultiPage'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

interface StubOptions {
  /** /api/multi/start 的业务响应 */
  startResp?: unknown
  /** /api/multi/start 的 HTTP 状态码 */
  startStatus?: number
  running?: boolean
  stations?: unknown[]
}

function stubFetch(opts: StubOptions = {}) {
  const {
    startResp = { ok: true, stations: 2 },
    startStatus = 200,
    running = false,
    stations = [],
  } = opts
  const fetchMock = vi.fn(async (input: unknown) => {
    const url = String(input)
    if (url === '/api/multi/start') return jsonResponse(startResp, startStatus)
    if (url === '/api/multi/stop') return jsonResponse({ ok: true })
    if (url.startsWith('/api/multi/status')) return jsonResponse({ ok: true, running, stations })
    if (url.startsWith('/api/multi/summary')) {
      return jsonResponse({
        ok: true,
        running,
        station_count: stations.length,
        total_clients: 0,
        uptime: 0,
        stations: [],
      })
    }
    if (url.startsWith('/api/status')) {
      return jsonResponse({ role: 'master', running: false, points: 0, schemaVersion: 1 })
    }
    return jsonResponse({ ok: true })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <MultiPage />
      </AntdApp>
    </QueryClientProvider>,
  )
}

function postsTo(fetchMock: ReturnType<typeof vi.fn>, path: string): Record<string, unknown>[] {
  return (fetchMock.mock.calls as unknown as [string, RequestInit][])
    .filter(([url, init]) => url === path && init?.method === 'POST')
    .map(([, init]) => JSON.parse(String(init.body)) as Record<string, unknown>)
}

/**
 * 面板里的 `report()` 会**同时**写 Alert 与 antd message 浮层（两者都在 document 里），
 * 所以断言「错误可见」时用 getAllByText 计数，不要用 getByText（会命中多个）。
 */
function expectVisible(re: RegExp): void {
  expect(screen.getAllByText(re).length).toBeGreaterThan(0)
}

const START_ALL = /启动全部启用站/

/**
 * 按可见文本找 antd Button。
 *
 * 不用 `getByRole('button', { name })`：可访问名计算会遍历整棵子树，
 * 在这个 antd 重型 DOM 下比 `getAllByText` + `closest` 贵一个量级。
 */
function findButton(re: RegExp): HTMLButtonElement {
  const btn = screen
    .getAllByText(re)
    .map((el) => el.closest('button'))
    .find((b): b is HTMLButtonElement => b !== null)
  if (!btn) throw new Error(`未找到按钮：${re}`)
  return btn
}


describe('MultiPage（T16 多站工作台）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('参数校验不通过时不发请求，并把问题摊到界面上', async () => {
    const fetchMock = stubFetch()
    renderPage()

    // 默认草稿两站 → 先把第一站的 station_id 清空
    fireEvent.change(screen.getByDisplayValue('station-1'), { target: { value: '' } })
    await waitFor(() => expect(screen.getByText(/项待修正/)).toBeInTheDocument())
    expectVisible(/第 1 行：station_id 必填/)

    fireEvent.click(findButton(START_ALL))

    await waitFor(() => expectVisible(/参数校验未通过/))
    expect(postsTo(fetchMock, '/api/multi/start')).toHaveLength(0)
  })

  it('校验通过时按启用集合下发，body 只含 stations 且不含本地 enabled 字段', async () => {
    const fetchMock = stubFetch({ startResp: { ok: true, stations: 1 } })
    renderPage()

    // 把第二站设为不参与
    fireEvent.click(screen.getByLabelText('参与本次启动-station-2'))
    fireEvent.click(findButton(START_ALL))

    await waitFor(() => expect(postsTo(fetchMock, '/api/multi/start')).toHaveLength(1))
    const body = postsTo(fetchMock, '/api/multi/start')[0]
    const stations = body.stations as Record<string, unknown>[]
    expect(Object.keys(body)).toEqual(['stations'])
    expect(stations).toHaveLength(1)
    expect(stations[0].station_id).toBe('station-1')
    expect('enabled' in stations[0]).toBe(false)
    await waitFor(() => expectVisible(/已启动 1 个站/))
  })

  it('后端业务失败（ok=false）会给出可见错误', async () => {
    stubFetch({ startResp: { ok: false, error: 'multi already running' } })
    renderPage()

    fireEvent.click(findButton(START_ALL))

    await waitFor(() => expectVisible(/启动失败：multi already running/))
  })

  it('后端 400（参数非法）会给出可见错误，不静默', async () => {
    stubFetch({ startResp: { ok: false, error: 'invalid port' }, startStatus: 400 })
    renderPage()

    fireEvent.click(findButton(START_ALL))

    await waitFor(() => expectVisible(/启动失败：invalid port/))
  })

  it('停止全部会下发 /api/multi/stop', async () => {
    const fetchMock = stubFetch({
      running: true,
      stations: [
        {
          station_id: 'station-1',
          station_name: '子站 1',
          port: 2404,
          common_addr: 1,
          running: true,
          client_count: 2,
          yx_count: 100,
          yc_count: 50,
          yk_count: 20,
          ym_count: 10,
          simulation_active: false,
        },
      ],
    })
    renderPage()

    await waitFor(() => expect(findButton(/停止全部/)).toBeEnabled())
    fireEvent.click(findButton(/停止全部/))

    await waitFor(() => expect(postsTo(fetchMock, '/api/multi/stop').length).toBeGreaterThan(0))
    await waitFor(() => expectVisible(/已停止全部站/))
  })

  it('运行中：配置字段冻结、聚合状态可见，切「参与本次启动」触发重建提示', async () => {
    const runningStations = [
      {
        station_id: 'station-1',
        station_name: '子站 1',
        port: 2404,
        common_addr: 1,
        running: true,
        client_count: 2,
        yx_count: 100,
        yc_count: 50,
        yk_count: 20,
        ym_count: 10,
        simulation_active: false,
      },
      {
        station_id: 'station-2',
        station_name: '子站 2',
        port: 2405,
        common_addr: 2,
        running: false,
        client_count: 0,
        yx_count: 100,
        yc_count: 50,
        yk_count: 20,
        ym_count: 10,
        simulation_active: true,
      },
    ]
    stubFetch({ running: true, stations: runningStations })
    renderPage()

    // 运行中：启动按钮禁用（等数据到位后再断言）
    await waitFor(() => expect(findButton(START_ALL)).toBeDisabled())

    // 聚合状态表里能看到两个站：
    // station-id 在「草稿卡片标题」和「聚合状态表行」各出现一次，故按次数断言
    expect(screen.getByText('聚合状态')).toBeInTheDocument()
    // 表头文本会同时出现在 <th> 与 rc-table 的 measure-cell 里，用 count 断言
    expectVisible(/点数 YX\/YC\/YK\/YM/)
    expect(screen.getAllByText('station-1').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('station-2').length).toBeGreaterThanOrEqual(2)

    // 运行中：配置输入框冻结
    expect(screen.getByDisplayValue('2404')).toBeDisabled()

    // 把 station-2 移出启用集合 → 出现未生效提示 + 重建按钮
    fireEvent.click(screen.getByLabelText('参与本次启动-station-2'))
    await waitFor(() => expect(screen.getByText('站集合与当前运行中的站不一致')).toBeInTheDocument())
    expect(findButton(/重建管理器以应用/)).toBeInTheDocument()
  })
})
