import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, askQuestionStream } from './client'

const enc = new TextEncoder()

function sseResponse(chunks: string[], status = 200): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(enc.encode(c)))
      controller.close()
    },
  })
  return new Response(stream, { status, headers: { 'Content-Type': 'text/event-stream' } })
}

const result = { answer: 'ok', found: true, sources: [], language: 'en', elapsed_ms: 1, route: 'text', steps: [] }

afterEach(() => vi.restoreAllMocks())

describe('askQuestionStream', () => {
  it('delivers steps in order and resolves with the result, even when events are split across chunks', async () => {
    const full =
      `event: step\ndata: ${JSON.stringify({ node: 'analyze', ms: 1, info: '' })}\n\n` +
      `event: step\ndata: ${JSON.stringify({ node: 'Привет-ключ', ms: 2, info: 'кириллица ✓' })}\n\n` +
      `event: result\ndata: ${JSON.stringify(result)}\n\n`
    // chunk boundaries fall in the middle of events and of multi-byte (Cyrillic) characters
    const bytes = enc.encode(full)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        new ReadableStream<Uint8Array>({
          start(c) {
            c.enqueue(bytes.slice(0, 37))
            c.enqueue(bytes.slice(37, 120))
            c.enqueue(bytes.slice(120))
            c.close()
          },
        }),
        { status: 200 },
      ),
    )
    const steps: string[] = []
    const res = await askQuestionStream('q', [], (n) => steps.push(n))
    expect(steps).toEqual(['analyze', 'Привет-ключ'])
    expect(res.answer).toBe('ok')
  })

  it('turns an error event into an ApiError with the server status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse([`event: error\ndata: ${JSON.stringify({ status: 503, message: 'down' })}\n\n`]),
    )
    await expect(askQuestionStream('q', [], () => {})).rejects.toMatchObject({ status: 503, message: 'down' })
  })

  it('fails clearly when the stream ends without a result', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(sseResponse([`event: step\ndata: {"node":"analyze"}\n\n`]))
    await expect(askQuestionStream('q', [], () => {})).rejects.toBeInstanceOf(ApiError)
  })

  it('maps FastAPI validation errors (detail is a list) to readable text, never "[object Object]"', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ msg: 'String should have at least 2 characters' }] }), { status: 422 }),
    )
    await expect(askQuestionStream('q', [], () => {})).rejects.toThrow('String should have at least 2 characters')
  })

  it('exposes the access-code marker on 401', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Access code required.', code: 'access_code_required' }), { status: 401 }),
    )
    await expect(askQuestionStream('q', [], () => {})).rejects.toMatchObject({ code: 'access_code_required', status: 401 })
  })

  it('reports an unreachable server without leaking internals', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(askQuestionStream('q', [], () => {})).rejects.toMatchObject({ status: 0 })
  })
})
