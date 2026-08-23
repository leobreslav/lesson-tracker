import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { fetchTestPeople, loginAsTestUser, logout } from './api'
import { forgetOrigin, homeToken, rememberOrigin, wayHome } from './devSwitch'
import { LANGUAGES } from './i18n'

/**
 * Меню пользователя в правом углу бара — одно на оба интерфейса.
 *
 * У учителя и ученика бары разные: разделы у них общего не имеют, и один
 * компонент с флагом «а этому не показывай» получился бы длиннее двух. А вот
 * правый угол одинаков — имя, адрес, язык, выход, — и второй его копии быть
 * не должно: язык переключается в одном месте, выход тоже.
 *
 * Профиль в списке есть только у того, у кого он есть: `profileTo` пустой —
 * пункт не рисуется.
 *
 * Последним пунктом — «войти как», и только на стенде разработки. Гугл-
 * аккаунтов на четырнадцать учеников не напасёшься, а плюс-адреса не
 * годятся вовсе: под алиасом в Google не войти. Список приезжает из
 * дев-двери, которой в проде нет: там запрос отвечает 404, и пункт не
 * появляется — это проверка фактом, а не переменной сборки.
 */

/** Закрытие по клику мимо и по Escape. */
function useDismissable(open, close) {
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined

    const onPointerDown = (event) => {
      if (ref.current && !ref.current.contains(event.target)) close()
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') close()
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, close])

  return ref
}

export { useDismissable }

export default function UserMenu({ user, profileTo = null, onLoggedOut, onLanguageChange }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  const close = useCallback(() => setOpen(false), [])
  const ref = useDismissable(open, close)

  // переход по ссылке закрывает меню
  useEffect(() => setOpen(false), [location.pathname])

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      // выйдя, домой возвращаться некуда: следующий вход — уже другая
      // история, и подсунутая ему чужая дорога назад увела бы не туда
      forgetOrigin()
      onLoggedOut()
    }
  }

  // имя и адрес — две строки одной кнопки: под именем в школе ходят тёзки,
  // а входят все через Google, и адрес — единственное, чем один «Иванов»
  // отличается от другого. Имени нет — остаётся адрес, и второй раз его
  // повторять незачем
  const name = user
    ? [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email
    : '…'
  const email = user && name !== user.email ? user.email : null

  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="secondary"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="who">
          <span className="name">{name}</span>
          {email && <span className="email">{email}</span>}
        </span>
        <span aria-hidden="true">▾</span>
      </button>

      {open && (
        <ul className="dropdown" role="menu">
          {profileTo && (
            <li role="none">
              <Link role="menuitem" to={profileTo}>
                {t('nav.profile')}
              </Link>
            </li>
          )}
          <li className="dropdown-languages" role="none">
            <span className="hint">{t('language.label')}</span>
            <div className="actions">
              {LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  type="button"
                  role="menuitem"
                  className={language.code === i18n.language ? 'chip active' : 'chip'}
                  onClick={() => onLanguageChange(language.code)}
                >
                  {language.label}
                </button>
              ))}
            </div>
          </li>
          <li role="none">
            <button type="button" role="menuitem" onClick={handleLogout}>
              {t('nav.logout')}
            </button>
          </li>

          <SwitchUser user={user} />
        </ul>
      )}
    </div>
  )
}


/**
 * «Войти как» — переключатель аккаунтов на стенде разработки.
 *
 * Берёт токен той же дверью, которой пользуются браузерные тесты, кладёт
 * его туда же, откуда его читает `App.jsx`, и перезагружает страницу: вид
 * пользователя решается на входе, и половинчатая смена личности без
 * перезагрузки означала бы учительскую оболочку вокруг ученика.
 */
function SwitchUser({ user }) {
  const { t } = useTranslation()
  const [people, setPeople] = useState(null)
  const home = wayHome(user)

  useEffect(() => {
    let cancelled = false

    fetchTestPeople(homeToken())
      .then((result) => !cancelled && setPeople(result.people))
      .catch(() => {
        // двери нет — значит это не стенд разработки, и пункта тоже нет
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (!people?.length) return null

  const enter = async (email) => {
    /*
     * Уходя, оставляем дорогу назад.
     *
     * Без неё «посмотреть чужими глазами» — билет в один конец: чтобы
     * вернуться, надо узнать себя в списке из семнадцати человек, а
     * суперпользователь там ничем не отмечен и стоит между учителями. На
     * стенде это выглядело как «я не могу вернуться в свою учётку».
     */
    if (user) {
      rememberOrigin({
        email: user.email,
        name:
          [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email,
        token: localStorage.getItem('authToken'),
      })
    }

    // домашним токеном, а не текущим: на закрытом контуре дверь спрашивает,
    // кто стучится, а стучится тут уже подменённый
    const { key } = await loginAsTestUser(email, homeToken())
    localStorage.setItem('authToken', key)
    window.location.assign('/')
  }

  /** Вернуться домой: свой токен цел, спрашивать дверь незачем. */
  const goHome = async () => {
    if (home?.token) {
      localStorage.setItem('authToken', home.token)
    } else if (home?.email) {
      // токен могли и не сохранить (приватный режим) — тогда та же дверь
      const { key } = await loginAsTestUser(home.email, homeToken())
      localStorage.setItem('authToken', key)
    }
    forgetOrigin()
    window.location.assign('/')
  }

  /*
   * Две группы, а не один список, и это чинит настоящую пропажу.
   *
   * Людей семнадцать, сотрудники идут первыми, а список прокручивается
   * (`max-height`) — и учеников за краем **не было видно вовсе**: у
   * прокрутки внутри выпадающего меню нет ни одного признака, что она
   * есть. Выглядело это как «на стенде нет ни одного ученика», хотя их
   * четырнадцать. Заголовок группы виден всегда (`sticky`) и говорит, что
   * список продолжается.
   */
  const roots = people.filter((person) => person.is_superuser)
  const staff = people.filter(
    (person) => !person.is_superuser && person.kind !== 'student',
  )
  const students = people.filter((person) => person.kind === 'student')

  const group = (title, list) =>
    list.length > 0 && (
      <>
        <li className="switch-group" role="none">
          {t(title)}
        </li>
        {list.map((person) => (
          <li key={person.email} role="none">
            <button type="button" role="menuitem" onClick={() => enter(person.email)}>
              {person.name}
              <span className="hint">{describeRole(person, t)}</span>
            </button>
          </li>
        ))}
      </>
    )

  return (
    <li className="dropdown-switch" role="none">
      <span className="hint">{t('devSwitch.label')}</span>

      {/* дорога домой — над списком и вне его прокрутки: искать её там же,
          где чужие лица, значит не найти */}
      {home && (
        <button type="button" role="menuitem" className="switch-home" onClick={goHome}>
          {t('devSwitch.back', { name: home.name })}
        </button>
      )}

      <ul>
        {/* суперпользователи первыми: их два раздела — школы и обращения —
            изнутри школы недостижимы, и возвращаются обычно именно сюда */}
        {group('devSwitch.roots', roots)}
        {group('devSwitch.staff', staff)}
        {group('devSwitch.students', students)}
      </ul>
    </li>
  )
}

const describeRole = (person, t) =>
  t(
    person.is_superuser
      ? 'devSwitch.root'
      : person.kind === 'student'
        ? 'devSwitch.student'
        : person.is_school_admin
          ? 'devSwitch.admin'
          : 'devSwitch.teacher',
  )
