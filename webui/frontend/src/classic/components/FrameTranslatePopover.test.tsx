import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FrameTranslatePopover } from './FrameTranslatePopover'

const HEX = '680e0400030064010600010000000014'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

const TRANSLATION = {
  ok: true,
  // 契约 §2.9：成功响应是扁平结构（format/segments 在顶层）
  format: 'I',
  segments: [
    { title: 'APCI（传输控制头）', lines: ['I 帧 | 发送序号 VS=2 接收序号 VR=1'] },
    {
      title: 'ASDU（C_IC_NA_1(100)）',
      lines: [
        'C_IC_NA_1(100) | VSQ=1 SQ=0 非连续 | COT=6 激活',
        '信息体 1: IOA 0 | QOI=20（站召唤）',
      ],
    },
  ],
}

describe('FrameTranslatePopover（悬停翻译，第二批改造④）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('悬停拉起翻译：渲染逐段标题与行', async () => {
    const fetchMock = vi.fn(async (input: unknown) => {
      expect(String(input)).toContain('/api/frames/decode?hex=')
      return jsonResponse(TRANSLATION)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <FrameTranslatePopover hex={HEX}>
        <span data-testid="cell">68 0E …</span>
      </FrameTranslatePopover>,
    )
    fireEvent.mouseEnter(screen.getByTestId('cell'))
    fireEvent.mouseOver(screen.getByTestId('cell'))
    await screen.findByText('APCI（传输控制头）', {}, { timeout: 4000 })
    expect(screen.getByText(/I 帧 \| 发送序号 VS=2/)).toBeInTheDocument()
    expect(screen.getByText(/QOI=20（站召唤）/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // 同 hex 缓存：重挂载不重复请求
    render(
      <FrameTranslatePopover hex={HEX}>
        <span data-testid="cell2">68 0E …</span>
      </FrameTranslatePopover>,
    )
    fireEvent.mouseEnter(screen.getByTestId('cell2'))
    await waitFor(() => expect(screen.getAllByText('APCI（传输控制头）').length).toBe(2))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('后端报错 → 展示翻译失败文案', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: false, error: '非法 HEX 串' })),
    )
    render(
      <FrameTranslatePopover hex="zz">
        <span data-testid="cell">zz</span>
      </FrameTranslatePopover>,
    )
    fireEvent.mouseEnter(screen.getByTestId('cell'))
    await screen.findByText(/翻译失败：非法 HEX 串/, {}, { timeout: 4000 })
  })
})
