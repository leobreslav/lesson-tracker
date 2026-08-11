import { useCallback, useState } from 'react'
import Dashboard from './Dashboard'
import Login from './Login'
import { clearToken, getToken } from './api'

export default function App() {
  // роутера нет: состояние входа само определяет, какой экран показывать
  const [token, setTokenState] = useState(getToken)

  const handleLoggedIn = useCallback(() => setTokenState(getToken()), [])

  const handleLoggedOut = useCallback(() => {
    clearToken()
    setTokenState(null)
    window.google?.accounts?.id?.disableAutoSelect()
  }, [])

  return token ? (
    <Dashboard onLoggedOut={handleLoggedOut} />
  ) : (
    <Login onLoggedIn={handleLoggedIn} />
  )
}
