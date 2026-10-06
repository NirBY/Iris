import { Route, Routes } from 'react-router-dom'
import { Layout } from './Layout'
import { useMe } from './lib/auth'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'

export function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return null
  if (!me) return <Login />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
      </Route>
    </Routes>
  )
}
