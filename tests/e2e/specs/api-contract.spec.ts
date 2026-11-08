/**
 * REST 响应契约 e2e（2026-11-07 引入）。
 *
 * 与前端**同一份** schema（`webui/frontend/src/api/contracts.ts`）对真实后端
 * 逐端点校验：后端字段改名/缺失/改类型会在 CI 直接失败，而不是等用户悬停
 * 后看到「翻译失败」。
 *
 * 为什么放在 Playwright：Vitest 跑在 jsdom、没有真实后端；这里的 `request`
 * 夹具直达 aiohttp + 真实引擎状态，是唯一能同时覆盖“前后端两侧”的层。
 */
import { expect, test } from '@playwright/test'

import {
  authProbeResponseSchema,
  captureFilesResponseSchema,
  captureFramesResponseSchema,
  captureStatusSchema,
  frameDecodeSchema,
  historyDataRecordSchema,
  historyFrameRecordSchema,
  historyRowsSchema,
  historyStatsResponseSchema,
  logsResponseSchema,
  multiStatusResponseSchema,
  multiSummaryResponseSchema,
  okSchema,
  paramStateResponseSchema,
  paramsResponseSchema,
  pointsResponseSchema,
  recentResponseSchema,
  schemaResponseSchema,
  sessionExportSchema,
  simulationStatusResponseSchema,
  statusSchema,
  testScriptsResponseSchema,
  testStatusResponseSchema,
} from '../../../webui/frontend/src/api/contracts'
import { IEC_PORT, MASTER, SLAVE, injectPoints, stopEngines, waitForStatus } from './helpers'

interface ContractCase {
  path: string
  schema: { parse: (value: unknown, path: string) => unknown }
}

/** 与后端状态无关、任何时刻都应返回合法形状的 GET 端点。 */
const GET_CASES: ContractCase[] = [
  { path: '/api/schema', schema: schemaResponseSchema },
  { path: '/api/auth', schema: authProbeResponseSchema },
  { path: '/api/status', schema: statusSchema },
  { path: '/api/points', schema: pointsResponseSchema },
  { path: '/api/recent', schema: recentResponseSchema },
  {
    // 真实 I 帧（C_IC_NA_1 总召唤激活）：扁平 {ok, format, segments}
    path: '/api/frames/decode?hex=680e0400030064010600010000000014',
    schema: frameDecodeSchema,
  },
  { path: '/api/frames/decode?hex=zz', schema: frameDecodeSchema },
  { path: '/api/master/param_state?ioa=1', schema: paramStateResponseSchema },
  { path: '/api/master/params', schema: paramsResponseSchema },
  { path: '/api/multi/status', schema: multiStatusResponseSchema },
  { path: '/api/multi/summary', schema: multiSummaryResponseSchema },
  { path: '/api/history/stats', schema: historyStatsResponseSchema },
  { path: '/api/history/data', schema: historyRowsSchema(historyDataRecordSchema) },
  { path: '/api/history/frames', schema: historyRowsSchema(historyFrameRecordSchema) },
  { path: '/api/simulation', schema: simulationStatusResponseSchema },
  { path: '/api/capture/status', schema: captureStatusSchema },
  { path: '/api/capture/files', schema: captureFilesResponseSchema },
  { path: '/api/capture/frames', schema: captureFramesResponseSchema },
  { path: '/api/tests/scripts', schema: testScriptsResponseSchema },
  { path: '/api/tests/status', schema: testStatusResponseSchema },
  { path: '/api/logs', schema: logsResponseSchema },
  { path: '/api/export/session.json', schema: sessionExportSchema },
]

async function assertContract(
  request: import('@playwright/test').APIRequestContext,
  base: string,
  path: string,
  schema: ContractCase['schema'],
): Promise<void> {
  const res = await request.get(`${base}${path}`)
  const body = (await res.json()) as unknown
  if (!res.ok()) {
    // 业务错误（如抓包未加载时 /api/capture/frames 返回 400）也属于契约：
    // 必须是 {ok:false, error:string}，不能是 500 或裸文本。
    expect(res.status(), `${path} 非 400 错误`).toBe(400)
    expect(body).toMatchObject({ ok: false })
    expect(typeof (body as { error?: unknown }).error).toBe('string')
    return
  }
  try {
    schema.parse(body, path)
  } catch (e) {
    throw new Error(`契约校验失败 ${path}: ${e instanceof Error ? e.message : String(e)}`)
  }
}

test.describe.configure({ mode: 'serial' })

test('主站：全部只读端点响应符合前端 schema', async ({ request }) => {
  for (const c of GET_CASES) {
    await assertContract(request, MASTER, c.path, c.schema)
  }
})

test('子站：状态/点表/模拟/抓包/测试/会话导出符合 schema', async ({ request }) => {
  const subset = GET_CASES.filter((c) =>
    [
      '/api/status',
      '/api/points',
      '/api/recent',
      '/api/simulation',
      '/api/capture/status',
      '/api/tests/status',
      '/api/logs',
      '/api/export/session.json',
    ].includes(c.path),
  )
  for (const c of subset) {
    await assertContract(request, SLAVE, c.path, c.schema)
  }
})

test('幂等停止命令：通用命令响应 {ok, error?}', async ({ request }) => {
  for (const base of [MASTER, SLAVE]) {
    for (const path of ['/api/master/stop', '/api/slave/stop', '/api/multi/stop']) {
      const res = await request.post(`${base}${path}`)
      // 部分端点在另一端角色下未注册/无意义，404 跳过；其余必须合法
      if (res.status() === 404) continue
      expect(res.ok(), `${base}${path} HTTP ${res.status()}`).toBeTruthy()
      okSchema.parse(await res.json(), path)
    }
  }
})

test.describe('连接后的动态响应', () => {
  test.beforeAll(async ({ request }) => {
    await stopEngines(request)
    await injectPoints(request, MASTER)
    await injectPoints(request, SLAVE)
    const slave = await request.post(`${SLAVE}/api/slave/start`, {
      data: { host: '0.0.0.0', port: IEC_PORT, addr: 1 },
    })
    expect((await slave.json()).ok).toBeTruthy()
    await waitForStatus(request, SLAVE, (s) => s.started === true)

    const master = await request.post(`${MASTER}/api/master/start`, {
      data: { host: '127.0.0.1', port: IEC_PORT, addr: 1 },
    })
    expect((await master.json()).ok).toBeTruthy()
    await waitForStatus(request, MASTER, (s) => s.running === true)
    await request.post(`${MASTER}/api/master/gi`, { data: {} })

    // 等真实报文进入 recent 缓冲（STARTDT / 总召应答）
    const deadline = Date.now() + 15_000
    while (Date.now() < deadline) {
      const res = await request.get(`${MASTER}/api/recent`)
      const body = (await res.json()) as { frames?: unknown[] }
      if ((body.frames?.length ?? 0) > 0) return
      await new Promise((r) => setTimeout(r, 200))
    }
    throw new Error('等待真实报文超时')
  })

  test.afterAll(async ({ request }) => {
    await stopEngines(request)
  })

  test('运行态：status/points/recent/参数状态/会话导出符合 schema', async ({ request }) => {
    for (const c of GET_CASES.filter((x) =>
      [
        '/api/status',
        '/api/points',
        '/api/recent',
        '/api/master/param_state?ioa=1',
        '/api/master/params',
        '/api/capture/status',
        '/api/export/session.json',
        '/api/frames/decode?hex=680e0400030064010600010000000014',
      ].includes(x.path),
    )) {
      await assertContract(request, MASTER, c.path, c.schema)
    }
  })
})
