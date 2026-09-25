/** Frontend smoke tests: typed API client + visual token maps.
 *
 * Run with: npm test (from frontend/)
 * These are node-environment tests (no DOM); component rendering is verified
 * manually via the dev server + preview during Phase 1.
 */
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'

import { fetchCities, fetchHealth, fetchRecords } from './api'

// Minimal Response stub good enough for our JSON client.
function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
  } as Response
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('api client', () => {
  it('fetchHealth hits /api/health and parses JSON', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', mode: 'demo' }))
    globalThis.fetch = mock as unknown as typeof fetch

    const data = await fetchHealth()

    expect(mock).toHaveBeenCalledWith('/api/health', expect.anything())
    expect(data.status).toBe('ok')
  })

  it('fetchCities encodes the endpoint correctly', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({ cities: [] }))
    globalThis.fetch = mock as unknown as typeof fetch

    await fetchCities()

    expect(mock.mock.calls[0][0]).toBe('/api/cities')
  })

  it('fetchRecords URL-encodes the city parameter', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({ records: [] }))
    globalThis.fetch = mock as unknown as typeof fetch

    await fetchRecords('new york')

    expect(mock.mock.calls[0][0]).toBe('/api/records?city=new%20york')
  })

  it('throws a clear error on non-2xx responses', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({}, false, 500)) as unknown as typeof fetch

    await expect(fetchHealth()).rejects.toThrow('API 500 on /health')
  })
})
