import { Route, Routes } from 'react-router-dom'
import { Layout } from './Layout'
import { useMe } from './lib/auth'
import { AlertDetail } from './pages/AlertDetail'
import { Alerts } from './pages/Alerts'
import { Chats } from './pages/Chats'
import { Dashboard } from './pages/Dashboard'
import { Instances } from './pages/Instances'
import { Jobs } from './pages/Jobs'
import { Login } from './pages/Login'
import { MessageContext } from './pages/MessageContext'
import { Messages } from './pages/Messages'
import { Review } from './pages/Review'
import { Settings } from './pages/Settings'

export function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return null
  if (!me) return <Login />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="alerts/:id" element={<AlertDetail />} />
        <Route path="review" element={<Review />} />
        <Route path="messages" element={<Messages />} />
        <Route path="messages/:id" element={<MessageContext />} />
        <Route path="chats" element={<Chats />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="instances" element={<Instances />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
