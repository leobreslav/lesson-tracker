import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import JournalTable from './JournalTable'
import MathText from './MathText'
import { Link, useParams } from 'react-router-dom'
import {
  fetchStudentCourse,
  fetchStudentJournal,
  fetchStudentWorks,
} from './api'
import { dateTime, weekdayWithDate } from './dates'

/**
 * Курс глазами ученика: учебный план и работы.
 *
 * До этого экрана ученик видел название курса и список работ — и на вопрос
 * «что мы вообще проходим» ответить было нечем. Теперь план курса открыт:
 * он **принадлежит курсу**, значит у ученика и учителя он один и тот же.
 * Пока план был личным, этого экрана нельзя было сделать честно: у двух
 * ведущих было два плана, и пришлось бы показывать чей-то один, не умея
 * объяснить чей.
 *
 * Показываются только названия и даты. Цели, ход урока, домашнее задание и
 * вложения остаются учительскими — это отдельное решение, и принимать его
 * заодно с этим экраном не надо.
 *
 * Год целиком, без окна: спрашивают здесь «что было и что будет», а не «что
 * на этой неделе».
 */
export default function StudentCourse({ onLoggedOut }) {
  const { id } = useParams()
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [works, setWorks] = useState([])
  const [journal, setJournal] = useState(null)
  /* Какую четверть смотрим. `null` — «решай сам»: сервер откроет ту, в
     которой идёт сегодняшний день, а в каникулы — прошедшую. */
  const [term, setTerm] = useState(null)
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

    // план и работы одним заходом: два состояния загрузки подряд мигают, а
    // порознь эти половины экрана не читаются
    Promise.all([fetchStudentCourse(id), fetchStudentWorks()])
      .then(([course, assigned]) => {
        if (cancelled) return
        setData(course)
        setWorks(assigned.works.filter((work) => String(work.course_id) === String(id)))
      })
      .catch((err) => !cancelled && handleError(err))

    return () => {
      cancelled = true
    }
  }, [id, handleError])

  /*
   * Журнал — отдельным запросом, и это не небрежность.
   *
   * План с работами приходят один раз, а четверть человек переключает, и
   * складывать их в один заход значило бы перечитывать план на каждое
   * нажатие. Ошибка сюда тоже не едет наверх: журнала может не быть вовсе
   * (год без разметки, курс без занятий), и вся страница из-за этого падать
   * не должна.
   */
  useEffect(() => {
    let cancelled = false

    fetchStudentJournal(id, term)
      .then((answer) => !cancelled && setJournal(answer))
      .catch(() => !cancelled && setJournal(null))

    return () => {
      cancelled = true
    }
  }, [id, term])

  if (data === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  const { course, lessons } = data
  const details = [course.subject, course.grade, course.teacher].filter(Boolean)

  return (
    <main className="page">
      <header className="page-header">
        <h1>{course.name}</h1>
        {details.length > 0 && <p className="hint">{details.join(' · ')}</p>}
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!course.active && <p className="hint warning">{t('student.past.hint')}</p>}

      {/*
        * Свой журнал: оценки и посещаемость по датам, одной строкой.
        *
        * Тот же расчёт и тот же рисунок, что у учителя, — разойдись они, и
        * родитель на собрании увидел бы не то, что учитель у себя. Отличий
        * два, и оба про право: строка одна, а отметка, которую учитель ещё не
        * разослал классу, сюда не приезжает вовсе.
        *
        * Ссылок на занятие тут нет: экрана занятия у ученика не существует, и
        * ссылка вела бы в пустоту.
        */}
      {journal && journal.columns.length > 0 && (
        <section className="panel">
          <h3>{t('journal.mine')}</h3>
          {(journal.terms ?? []).length > 0 && (
            <div className="year-picker">
              {journal.terms.map((one) => (
                <button
                  key={one.id}
                  type="button"
                  className={`chip ${String(journal.term) === String(one.id) ? 'on' : ''}`}
                  onClick={() => setTerm(one.id)}
                >
                  {one.name}
                </button>
              ))}
              <button
                type="button"
                className={`chip ${journal.term === null ? 'on' : ''}`}
                onClick={() => setTerm('all')}
              >
                {t('journal.wholeYear')}
              </button>
            </div>
          )}
          <JournalTable journal={journal} lessonLinks={false} />
        </section>
      )}

      <section className="panel">
        <h3>{t('student.course.plan')}</h3>
        {lessons.length === 0 ? (
          <p className="hint">{t('student.course.noPlan')}</p>
        ) : (
          <ol className="student-plan">
            {lessons.map((row) => (
              <li
                key={row.id}
                className={rowClass(row)}
                data-lesson={row.is_section ? undefined : row.number}
              >
                {row.is_section ? (
                  <span className="theme">
                    <MathText text={row.title} />
                  </span>
                ) : (
                  <>
                    <span className="number">{row.number}</span>
                    {/* та же отрисовка, что у учителя и методиста: доллары
                        вместо формулы — это план, показанный хуже, чем он
                        написан */}
                    <span className="title">
                      <MathText text={row.title} />
                    </span>
                    {/* урока без даты не бывает «неправильного»: плану
                        просто не хватило дней, и это разговор учителя с
                        методистом, а не с учеником */}
                    <span className="date">
                      {row.date ? weekdayWithDate(row.date) : ''}
                    </span>
                  </>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="panel">
        <h3>{t('student.course.works')}</h3>
        {works.length === 0 ? (
          <p className="hint">{t('student.course.noWorks')}</p>
        ) : (
          <ul className="work-links">
            {works.map((work) => (
              <li key={work.id}>
                <Link to={`/works/${work.id}`}>{work.title}</Link>
                <span className={`badge state-${work.state}`}>
                  {t(`works.state.${work.state}`)}
                </span>
                <span className="hint">
                  {t('student.work.progress', {
                    answered: work.answered,
                    tasks: work.tasks,
                  })}
                </span>
                <span className="hint">
                  {t(work.state === 'open' ? 'student.work.until' : 'student.work.was', {
                    moment: dateTime(work.closes_at),
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p>
        <Link to="/">{t('student.title')}</Link>
      </p>
    </main>
  )
}

/** Прошедшее приглушено: по нему видно, где класс сейчас. */
function rowClass(row) {
  if (row.is_section) return 'section'
  return row.past ? 'past' : ''
}
