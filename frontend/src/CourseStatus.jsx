import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import CourseRow from './CourseRow'
import { fetchProgress } from './api'

/**
 * Состояние курсов — блок главной страницы, а не отдельный раздел.
 *
 * Своим экраном это было, и экран был правильный, но заходить на него
 * приходилось нарочно: «как идут дела» — это первый вопрос дня, и отвечать
 * на него должна страница, которая открывается сама. Главная как раз и
 * отвечала на него хуже — списком классов с одним числом в строке.
 *
 * Ленту с датами забрал себе учебный план: там она рабочая, там же её и
 * правят. Здесь остаётся то, чего в плане нет и не должно быть: где курс
 * идёт сейчас, успевает ли и что впереди — и всё это **сразу по всем
 * курсам**. План всегда про один курс, этот блок про все: учитель ведёт
 * пять и хочет одним взглядом понять, где проблема.
 *
 * Числа приходят одним запросом `/api/plan/progress/`, который считает их
 * тем же `build_layout`, что и остальные ответы про раскладку. Своих
 * расчётов здесь нет вовсе — иначе они однажды разошлись бы с планом.
 *
 * Данные берёт сам, а не получает пропсом: у главной свой запрос состояния
 * (`/api/onboarding/status/`), и мешать их в один — значит заставлять
 * шаги первого входа ждать раскладку по всем курсам.
 */
export default function CourseStatus({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [courses, setCourses] = useState(null)
  const [opened, setOpened] = useState(null)
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

    fetchProgress()
      .then((result) => {
        if (cancelled) return
        setCourses(result.courses)
        // разворачиваем тот, где проблема: экран затем и нужен, чтобы её
        // увидеть. Проблем нет — все свёрнуты, смотреть не на что
        const trouble = result.courses.find((course) => course.reserve < 0)
        if (trouble) setOpened(trouble.id)
        else if (result.courses.length === 1) setOpened(result.courses[0].id)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  if (courses === null) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  // курсов нет вовсе — на главной об этом уже сказали шаги первого входа,
  // и второй раз повторять незачем
  if (!courses.length) return null

  return (
    <>
      <h2 className="section-title">{t('status.title')}</h2>
      <p className="hint">{t('status.hint')}</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <ul className="progress-list">
        {courses.map((course) => (
          <CourseRow
            key={course.id}
            row={course}
            own
            open={opened === course.id}
            onToggle={() => setOpened(opened === course.id ? null : course.id)}
            actions={
              <div className="actions wrap">
                <button type="button" onClick={() => navigate('/plan')}>
                  {t('status.toPlan')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => navigate('/schedule')}
                >
                  {t('status.toSchedule')}
                </button>
              </div>
            }
          />
        ))}
      </ul>
    </>
  )
}
