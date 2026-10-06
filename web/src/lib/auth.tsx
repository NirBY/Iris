import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api<{ username: string }>('/api/auth/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    retry: false,
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return async () => {
    await api('/api/auth/logout', { method: 'POST' })
    await qc.invalidateQueries({ queryKey: ['me'] })
  }
}
