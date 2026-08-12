import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Agenda from './Agenda'
import Calendar from './Calendar'
import Classes from './Classes'
import Dashboard from './Dashboard'
import Layout from './Layout'
import Login from './Login'
import NavBar from './NavBar'
import NotFound from './NotFound'
import Plan from './Plan'
import Profile from './Profile'
import { clearToken, fetchMe, getToken } from './api'

export default function App() {
  const [token, setTokenState] = useState(getToken)
  // имя для бара: страницы за своими данными ходят сами
  const [user, setUser] = useState(null)

  const handleLoggedIn = useCallback(() => setTokenState(getToken()), [])

  const handleLoggedOut = useCallback(() => {
    clearToken()
    setTokenState(null)
    setUser(null)
    window.google?.accounts?.id?.disableAutoSelect()
  }, [])

  useEffect(() => {
    if (!token) return undefined

    let cancelled = false
    fetchMe()
      .then((data) => {
        if (!cancelled) setUser(data)
      })
      .catch((err) => {
        // токен протух — возвращаемся на логин
        if (err.status === 401) handleLoggedOut()
      })

    return () => {
      cancelled = true
    }
  }, [token, handleLoggedOut])

  // на логине бара нет: показывать в нём нечего и некому
  if (!token) return <Login onLoggedIn={handleLoggedIn} />

  const guarded = (Page, props) => <Page onLoggedOut={handleLoggedOut} {...props} />

  return (
    <BrowserRouter>
      <NavBar user={user} onLoggedOut={handleLoggedOut} />

      <Routes>
        <Route path="/" element={<Dashboard user={user} />} />
        <Route path="/schedule" element={guarded(Agenda)} />
        <Route path="/layout" element={guarded(Layout)} />
        <Route path="/plan" element={guarded(Plan)} />
        <Route path="/classes" element={guarded(Classes)} />
        <Route path="/year" element={guarded(Calendar)} />
        <Route path="/profile" element={guarded(Profile, { onSaved: setUser })} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  )
}
