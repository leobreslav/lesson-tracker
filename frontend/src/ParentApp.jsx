import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import EmptyState from './EmptyState'
import ErrorBoundary from './ErrorBoundary'
import Messenger from './Messenger'
import FeedbackButton from './FeedbackButton'
import StudentCourse from './StudentCourse'
import StudentWork from './StudentWork'
import UserMenu from './UserMenu'
import { StudentCourses } from './StudentApp'
import { fetchChildren } from './api'
import { setViewedChild, viewedChild } from './viewedChild'

/**
 * Интерфейс родителя — третья ветка входа, а не роль внутри ученической.
 *
 * Экраны про учёбу он берёт у ученика **целиком** и не копирует: курсы, курс,
 * работа — те же самые страницы, тот же код, те же запросы. Отличается
 * ровно одно, и живёт оно не здесь, а в `viewedChild`: адреса носят
 * `?child=`, и сервер отвечает про ребёнка. Скопировать четыре страницы
 * «для родителя» значило бы завести четыре места, которые разъедутся, — а
 * разъехавшись, покажут родителю не то, что видит ребёнок, и никто этого не
 * заметит.
 *
 * Своего у родителя два: **выбор ребёнка** и **разговор с учителем**. Первое
 * стоит в баре — оно относится ко всему, что ниже; второе отдельным
 * разделом, потому что это его переписка, а не сведения об учёбе.
 *
 * Выбор показывается только при нескольких детях. У одного ребёнка селект из
 * одной строки — это вопрос без второго ответа, и место он занимает зря.
 */
export default function ParentApp({ user, onLoggedOut, onLanguageChange }) {
  const { t } = useTranslation()
  const [children, setChildren] = useState(null)
  const [current, setCurrent] = useState(() => viewedChild())
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    let cancelled = false

    fetchChildren()
      .then((answer) => {
        if (cancelled) return
        setChildren(answer.children)
        // Выбор чинится здесь, а не при чтении: сохранённый ребёнок мог
        // выпасть из списка (связь сняли), и запрос с его номером получил бы
        // `not_your_child` на каждом экране. Пустой выбор при одном ребёнке
        // тоже чиним — иначе сервер переспрашивал бы зря.
        const known = answer.children.some((one) => String(one.id) === String(current))
        if (!known) {
          const first = answer.children.length === 1 ? answer.children[0].id : ''
          setViewedChild(first)
          setCurrent(first)
        }
      })
      .catch((err) => !cancelled && handleError(err))

    return () => {
      cancelled = true
    }
    // намеренно один раз: список детей меняет администратор, и следить за
    // ним опросом — не то, ради чего родитель открыл страницу
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handleError])

  const pick = (id) => {
    setViewedChild(id)
    setCurrent(id)
  }

  return (
    <BrowserRouter>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            {t('app.name')}
          </Link>

          <nav className="topbar-nav">
            <Link to="/">{t('parent.study')}</Link>
            <Link to="/chat">{t('parent.chat')}</Link>
          </nav>

          <div className="topbar-right">
            {children && children.length > 1 && (
              <label className="child-picker">
                <span className="hint">{t('parent.child')}</span>
                <select
                  value={current ?? ''}
                  onChange={(event) => pick(event.target.value)}
                >
                  <option value="">{t('parent.pickChild')}</option>
                  {children.map((child) => (
                    <option key={child.id} value={child.id}>
                      {child.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <FeedbackButton compact />
            <UserMenu
              user={user}
              onLoggedOut={onLoggedOut}
              onLanguageChange={onLanguageChange}
            />
          </div>
        </div>
      </header>

      <ErrorBoundary>
        {error && (
          <main className="page">
            <p className="error">{error}</p>
          </main>
        )}

        {children !== null && children.length === 0 ? (
          <main className="page">
            <EmptyState title={t('parent.noChildren.title')}>
              {t('parent.noChildren.hint')}
            </EmptyState>
          </main>
        ) : children !== null && children.length > 1 && !current ? (
          /* Несколько детей и никто не выбран — сервер на этом честно
             переспрашивает (`child_required`), и показывать вместо ответа
             ошибку на каждом экране было бы хуже, чем спросить здесь */
          <main className="page">
            <EmptyState title={t('parent.pickChild')}>
              {t('parent.pickChildHint')}
            </EmptyState>
          </main>
        ) : (
          <Routes>
            <Route path="/" element={<StudentCourses onLoggedOut={onLoggedOut} />} />
            <Route
              path="/courses/:id"
              element={<StudentCourse onLoggedOut={onLoggedOut} />}
            />
            <Route path="/works/:id" element={<StudentWork />} />
            <Route
              path="/chat"
              element={<Messenger onLoggedOut={onLoggedOut} />}
            />
            <Route path="*" element={<ParentNotFound />} />
          </Routes>
        )}
      </ErrorBoundary>
    </BrowserRouter>
  )
}

function ParentNotFound() {
  const { t } = useTranslation()
  return (
    <main className="page">
      <EmptyState title={t('notFound.title')}>
        <Link to="/">{t('notFound.home')}</Link>
      </EmptyState>
    </main>
  )
}
