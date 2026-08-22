import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import CoursePicker from './CoursePicker'
import MathText from './MathText'
import { fetchChronology, fetchCourses, fetchTags, forgetTag, introduceTag } from './api'
import { lastChoice, rememberChoice } from './remember'

/**
 * План курса как хронология понятий.
 *
 * Отвечает на вопрос, которого до сих пор задать было негде: **что класс уже
 * умеет**. Учебный план говорит, какие темы прошли, а решения размечены тем,
 * чем они пользуются, — связывает эти две разметки одна отметка: «этот урок
 * вводит это понятие».
 *
 * Показывается план целиком, а не по уроку: смысл у списка появляется, только
 * когда виден **порядок** — «производная в марте, а задача на неё в октябре».
 * По той же причине это отдельная страница, а не блок в окне правки урока: в
 * окне видно одну строку, а размечают хронологию, глядя на весь год.
 *
 * Роль одна — «вводит». Обсуждались «повторяет» и «использует», и обе отпали:
 * первая ни на что не влияет, вторая выводится из решений, которые уже
 * размечены.
 */
export default function BankChronology() {
  const { t } = useTranslation()
  const [courses, setCourses] = useState([])
  const [course, setCourse] = useState(lastChoice('course'))
  const [lessons, setLessons] = useState(null)
  const [vocabulary, setVocabulary] = useState([])
  const [adding, setAdding] = useState(null) // id строки плана
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list)
        setCourse((now) => (list.some((one) => one.id === now) ? now : list[0]?.id))
      })
      .catch((problem) => setError(problem.message))
    fetchTags()
      .then((answer) => setVocabulary(answer.tags))
      .catch(() => setVocabulary([]))
  }, [])

  const load = useCallback(() => {
    if (!course) return
    fetchChronology(course)
      .then((answer) => setLessons(answer.lessons))
      .catch((problem) => setError(problem.message))
  }, [course])

  useEffect(() => {
    load()
    if (course) rememberChoice('course', course)
  }, [course, load])

  const add = async (node, tag) => {
    setAdding(null)
    try {
      const answer = await introduceTag(course, node, Number(tag))
      setLessons(answer.lessons)
    } catch (problem) {
      setError(problem.message)
    }
  }

  const forget = async (tag) => {
    try {
      await forgetTag(course, tag)
      load()
    } catch (problem) {
      setError(problem.message)
    }
  }

  return (
    <main className="page wide">
      <header className="page-header spread">
        <h1>
          {t('bank.chronology.title')}
          <CoursePicker courses={courses} value={course} onChange={setCourse} />
        </h1>
        <Link to="/bank">{t('bank.title')}</Link>
      </header>

      {error && <p className="error">{error}</p>}
      <p className="hint">{t('bank.chronology.hint')}</p>

      {lessons && lessons.length === 0 && (
        <p className="hint">{t('bank.chronology.noPlan')}</p>
      )}

      <ul className="chronology">
        {(lessons || []).map((lesson) => (
          <li key={lesson.node}>
            <span className="label">{lesson.number}</span>
            <span className="text">
              <MathText text={lesson.title} />
            </span>
            <span className="tags">
              {lesson.tags.map((tag) => (
                <button
                  key={tag.id}
                  type="button"
                  className="tag"
                  title={t('bank.chronology.forget')}
                  onClick={() => forget(tag.id)}
                >
                  {tag.name} ✕
                </button>
              ))}
              {adding === lesson.node ? (
                <select
                  autoFocus
                  aria-label={t('bank.expression.tag')}
                  defaultValue=""
                  onChange={(event) => add(lesson.node, event.target.value)}
                  onBlur={() => setAdding(null)}
                >
                  <option value="" disabled>
                    —
                  </option>
                  {vocabulary.map((tag) => (
                    <option key={tag.id} value={tag.id}>
                      {tag.name}
                    </option>
                  ))}
                </select>
              ) : (
                <button type="button" className="link" onClick={() => setAdding(lesson.node)}>
                  {t('bank.chronology.add')}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </main>
  )
}
