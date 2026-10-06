import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from './lib/api'
import { useLogout, useMe } from './lib/auth'

export function Layout() {
  const { data: me } = useMe()
  const logout = useLogout()
  const { data: v } = useQuery({
    queryKey: ['version'],
    queryFn: () => api<{ version: string }>('/api/version'),
  })
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <nav className="flex items-center gap-4 text-sm">
          <span className="font-semibold">Iris</span>
          {[
            ['/', 'Dashboard'],
            ['/messages', 'Messages'],
            ['/instances', 'Instances'],
          ].map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                isActive ? 'font-medium underline' : 'text-slate-600 dark:text-slate-400'
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <span className="flex items-center gap-3 text-sm">
          {me?.username}
          <button className="underline" onClick={logout}>
            Sign out
          </button>
        </span>
      </header>
      <main className="flex-1 p-4">
        <Outlet />
      </main>
      <footer className="px-4 py-2 text-xs text-slate-500">Iris {v?.version ?? ''}</footer>
    </div>
  )
}
