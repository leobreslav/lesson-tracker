import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import CoursePicker from './CoursePicker'
import EmptyState from './EmptyState'
import JournalTable from './JournalTable'
import { fetchCourses, fetchJournal } from './api'
import { lastChoice, rememberChoice, useKept } from './remember'

/**
 * Журнал курса: как идут дела у класса — одним экраном.
 *
 * Экрана этого не было, а вопрос задают чаще прочих: на собрании, на педсовете
 * и просто в конце четверти. Ответ до сих пор был разложен по страницам работ:
 * тридцать переходов вместо одного взгляда, и посещаемость при этом жила ещё и
 * на третьем экране — внутри занятия.
 *
 * **Терм, а не год.** За год у курса от тридцати до семидесяти занятий, и всё
 * это в одну таблицу лезет только с горизонтальной прокруткой; таблица, в
 * которую въезжают стрелками, отвечает на вопрос хуже, чем таблица, в которую
 * попадают глазами. Год целиком остаётся отдельной кнопкой — он отвечает на
 * другой вопрос: не «как идёт четверть», а «как прошёл год».
 *
 * Выбранный терм переживает уход со страницы и возврат назад, но не закрытие
 * вкладки: это поза за работой, а не настройка. Тот же `useKept`, что у
 * недели в расписании.
 */
export default function Journal({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [courses, setCourses] = useState(null)
  const [courseId, setCourseId] = useState(null)
  const [term, setTerm] = useKept('journalTerm', null)
  const [journal, setJournal] = useState(null)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list)
        // ключ выбора общий с планом и работами: работают обычно в одном курсе
        setCourseId((current) => {
          const remembered = lastChoice('course')
          const known = (id) => list.some((item) => item.id === id)
          if (current && known(current)) return current
          if (known(remembered)) return remembered
          return list[0]?.id ?? null
        })
      })
      .catch(handleError)
  }, [handleError])

  useEffect(() => {
    if (!courseId) return
    setJournal(null)
    /*
     * `term === null` — «решай сам»: сервер откроет ту четверть, в которой
     * идёт сегодняшний день, а в каникулы — прошедшую. Обратно в состояние
     * это не записывается намеренно: запиши — и выбор человека стал бы
     * неотличим от умолчания, а назавтра страница открылась бы во вчерашней
     * четверти, которую никто не выбирал. Подсвечивается поэтому то, что
     * **ответил сервер** (`journal.term`), а не то, что мы просили.
     */
    fetchJournal(courseId, term).then(setJournal).catch(handleError)
  }, [courseId, term, handleError])

  if (courses === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  const pickCourse = (id) => {
    setCourseId(id)
    rememberChoice('course', id)
  }

  const terms = journal?.terms ?? []

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('journal.title')}</h1>
        <CoursePicker courses={courses} value={courseId} onChange={pickCourse} />
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!courses.length ? (
        <EmptyState
          title={t('journal.needCourse.title')}
          actions={
            <button type="button" onClick={() => navigate('/school/courses')}>
              {t('plan.needClass.action')}
            </button>
          }
        >
          {t('journal.needCourse.hint')}
        </EmptyState>
      ) : (
        <>
          {/* Четверти чипами: их две-четыре, и выбирают из них глазами, а не
              раскрытием списка. «Весь год» стоит последним и намеренно
              отделён — это не пятая четверть, а другой вопрос. */}
          {terms.length > 0 && (
            <div className="year-picker">
              {terms.map((one) => (
                <button
                  key={one.id}
                  type="button"
                  className={`chip ${String(journal?.term) === String(one.id) ? 'on' : ''}`}
                  onClick={() => setTerm(one.id)}
                >
                  {one.name}
                </button>
              ))}
              <button
                type="button"
                className={`chip ${journal && journal.term === null ? 'on' : ''}`}
                onClick={() => setTerm('all')}
              >
                {t('journal.wholeYear')}
              </button>
            </div>
          )}

          <section className="panel">
            {journal === null ? (
              <p className="hint">{t('common.loading')}</p>
            ) : journal.students.length === 0 ? (
              <p className="hint">{t('journal.noStudents')}</p>
            ) : (
              <JournalTable journal={journal} />
            )}
          </section>
        </>
      )}
    </main>
  )
}
