import { Route, Routes } from 'react-router-dom'
import { Layout } from './Layout'
import { useMe } from './lib/auth'
import { Dashboard } from './pages/Dashboard'
import { Instances } from './pages/Instances'
import { Login } from './pages/Login'
import { MessageContext } from './pages/MessageContext'
import { Messages } from './pages/Messages'
import { Settings } from './pages/Settings'

export function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return null
  if (!me) return <Login />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="messages" element={<Messages />} />
        <Route path="messages/:id" element={<MessageContext />} />
        <Route path="instances" element={<Instances />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
