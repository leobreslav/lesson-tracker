import { useCallback, useState } from 'react'
import Dashboard from './Dashboard'
import Login from './Login'
import Profile from './Profile'
import { clearToken, getToken } from './api'

export default function App() {
  // роутера нет: состояние входа само определяет, какой экран показывать
  const [token, setTokenState] = useState(getToken)
  const [page, setPage] = useState('home')

  const handleLoggedIn = useCallback(() => {
    setPage('home')
    setTokenState(getToken())
  }, [])

  const handleLoggedOut = useCallback(() => {
    clearToken()
    setTokenState(null)
    setPage('home')
    window.google?.accounts?.id?.disableAutoSelect()
  }, [])

  const goHome = useCallback(() => setPage('home'), [])
  const goProfile = useCallback(() => setPage('profile'), [])

  if (!token) return <Login onLoggedIn={handleLoggedIn} />

  if (page === 'profile') {
    return <Profile onBack={goHome} onLoggedOut={handleLoggedOut} />
  }

  return <Dashboard onOpenProfile={goProfile} onLoggedOut={handleLoggedOut} />
}
