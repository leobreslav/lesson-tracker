import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import CoursePicker from './CoursePicker'
import MathText from './MathText'
import { fetchChronology, fetchCourses, fetchTopic, fetchTopics } from './api'
import { lastChoice } from './remember'

/**
 * Тематический каталог: папки, заданные условием.
 *
 * Жёсткий каталог — это источники, где задача лежит по адресу «книга, раздел,
 * номер». Здесь наоборот: тема это условие на средства разбора, и список её
 * пополняется сам, когда кто-то напишет новое решение.
 *
 * У закрытой темы есть второй вопрос — **«а что из этого мы умеем»**, — и
 * отвечает на него хронология курса. Поэтому рядом стоят выбор курса и урока:
 * без них закрытая тема отвечает «ничего», и это правда, просто бесполезная.
 */
export default function BankTopics() {
  const { t } = useTranslation()
  const [topics, setTopics] = useState([])
  const [chosen, setChosen] = useState(null)
  const [found, setFound] = useState(null)
  const [courses, setCourses] = useState([])
  const [course, setCourse] = useState(lastChoice('course'))
  const [lessons, setLessons] = useState([])
  const [upto, setUpto] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchTopics()
      .then((answer) => {
        setTopics(answer.topics)
        setChosen(answer.topics[0]?.id ?? null)
      })
      .catch((problem) => setError(problem.message))
    fetchCourses()
      .then((list) => {
        setCourses(list)
        setCourse((now) => (list.some((one) => one.id === now) ? now : list[0]?.id))
      })
      .catch(() => setCourses([]))
  }, [])

  useEffect(() => {
    if (!course) return
    fetchChronology(course)
      .then((answer) => setLessons(answer.lessons))
      .catch(() => setLessons([]))
  }, [course])

  useEffect(() => {
    if (!chosen) return
    fetchTopic(chosen, { course, upto: upto || undefined })
      .then(setFound)
      .catch((problem) => setError(problem.message))
  }, [chosen, course, upto])

  return (
    <main className="page wide">
      <header className="page-header spread">
        <h1>{t('bank.topics.title')}</h1>
        <Link to="/bank">{t('bank.title')}</Link>
      </header>

      {error && <p className="error">{error}</p>}

      {topics.length === 0 ? (
        <p className="hint">{t('bank.topics.none')}</p>
      ) : (
        <div className="bank-columns">
          <section className="panel">
            <h2>{t('bank.topics.title')}</h2>
            <ul className="outline">
              {topics.map((topic) => (
                <li key={topic.id} style={{ paddingLeft: `${topic.depth * 0.9}rem` }}>
                  <button
                    type="button"
                    className={`link ${topic.id === chosen ? 'active' : ''}`}
                    onClick={() => setChosen(topic.id)}
                  >
                    {topic.title}
                  </button>
                  {topic.closed && <span className="hint"> · {t('bank.topics.closed')}</span>}
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-head spread">
              <h2>{found ? found.title : t('common.loading')}</h2>
              {found?.closed && (
                <div className="row">
                  <CoursePicker courses={courses} value={course} onChange={setCourse} />
                  <label className="field">
                    <span>{t('bank.topics.upto')}</span>
                    <select value={upto} onChange={(event) => setUpto(event.target.value)}>
                      <option value="">{t('bank.topics.wholeYear')}</option>
                      {lessons.map((lesson) => (
                        <option key={lesson.node} value={lesson.node}>
                          {lesson.number}. {lesson.title}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
            </div>

            {found && (
              <p className="hint">
                {found.essence.map((tag) => tag.name).join(' · ')}
                {found.forbidden.length > 0 &&
                  ` · ${t('bank.without')} ${found.forbidden.map((tag) => tag.name).join(', ')}`}
              </p>
            )}

            <ul className="problem-list">
              {(found ? found.problems : []).map((problem) => (
                <li key={problem.id}>
                  <span className="label" />
                  <span className="text">
                    <Link to={`/bank/problem/${problem.id}`}>
                      <MathText text={problem.text} />
                    </Link>
                  </span>
                </li>
              ))}
            </ul>

            {found && found.total === 0 && (
              <p className="hint">
                {found.closed ? t('bank.topics.nothingYet') : t('bank.topics.nothing')}
              </p>
            )}
          </section>
        </div>
      )}
    </main>
  )
}
