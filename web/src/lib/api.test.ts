import { api, ApiError } from './api'

test('successful deletion with no content resolves without parsing JSON', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(null, { status: 204 })),
  )
  await expect(api('/api/instances/1', { method: 'DELETE' })).resolves.toBeUndefined()
})

test('JSON responses still return their body', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ id: 1 }), { status: 200 })),
  )
  await expect(api('/api/instances/1')).resolves.toEqual({ id: 1 })
})

test('failed deletion remains an API error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'Phone not found' }), { status: 404 })),
  )
  await expect(api('/api/instances/1', { method: 'DELETE' })).rejects.toBeInstanceOf(ApiError)
})
