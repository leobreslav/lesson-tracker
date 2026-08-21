import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Basket from './Basket'
import CoursePicker from './CoursePicker'
import MathText from './MathText'
import Pick from './Pick'
import ExpressionEditor from './ExpressionEditor'
import {
  deleteTopic,
  fetchChronology,
  fetchCourses,
  fetchTags,
  fetchTopic,
  fetchTopics,
  saveTopic,
  updateTopic,
} from './api'
import { lastChoice } from './remember'
import { prune } from './expressionTree'
import { taken } from './basket'

/**
 * Динамический каталог: папки, заданные условием.
 *
 * Жёсткий каталог — это источники, где задача лежит по адресу «книга, раздел,
 * номер». Здесь наоборот: тема это условие на средства разбора, и список её
 * пополняется сам, когда кто-то напишет новое решение.
 *
 * **Тема и сохранённый поиск — одно и то же**: названное условие с местом в
 * дереве. Общие ведёт суперпользователь, свои человек называет как хочет, и
 * своя ветка может висеть внутри общей — тогда она её сужает. Вложение здесь
 * значит именно сужение: условие ребёнка включает родительское целиком, и
 * потому внутри «Квадратных уравнений» тема называется просто «через Виета».
 *
 * У темы про пройденное есть второй вопрос — **«а что из этого мы умеем»**, — и
 * отвечает на него хронология курса. Поэтому рядом стоят выбор курса и урока:
 * без них такая тема отвечает «ничего», и это правда, просто бесполезная.
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
  const [picked, setPicked] = useState(taken())
  const [vocabulary, setVocabulary] = useState([])
  const [editing, setEditing] = useState(null) // {id, title, expression}
  const [busy, setBusy] = useState(false)

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
    fetchTags()
      .then((answer) => setVocabulary(answer.tags))
      .catch(() => setVocabulary([]))
  }, [])

  const reload = () =>
    fetchTopics()
      .then((answer) => setTopics(answer.topics))
      .catch((problem) => setError(problem.message))

  const run = async (what) => {
    setBusy(true)
    setError(null)
    try {
      await what
      await reload()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

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
        <div className="row">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() =>
              setEditing({ title: '', expression: { all: [] }, parent: chosen })
            }
          >
            {t('bank.topics.add')}
          </button>
          <Link to="/bank">{t('bank.title')}</Link>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      <Basket picked={picked} onChange={setPicked} />

      {editing && (
        <section className="panel">
          <div className="row">
            <label className="field">
              <span>{t('bank.topics.name')}</span>
              <input
                autoFocus
                value={editing.title}
                onChange={(event) =>
                  setEditing({ ...editing, title: event.target.value })
                }
              />
            </label>
            {editing.parent != null && (
              <span className="hint">
                {t('bank.topics.inside', {
                  name:
                    topics.find((one) => one.id === editing.parent)?.title ?? '',
                })}
              </span>
            )}
          </div>

          <ExpressionEditor
            node={editing.expression}
            tags={vocabulary}
            onChange={(next) =>
              setEditing({ ...editing, expression: next || { all: [] } })
            }
          />

          <div className="row">
            <button
              type="button"
              disabled={busy || !editing.title.trim()}
              onClick={() =>
                run(
                  (editing.id ? updateTopic(editing.id, {
                    title: editing.title,
                    expression: prune(editing.expression) || {},
                  }) : saveTopic({
                    title: editing.title,
                    expression: prune(editing.expression) || {},
                    parent: editing.parent ?? null,
                  })).then(() => setEditing(null)),
                )
              }
            >
              {t('common.save')}
            </button>
            <button type="button" className="link" onClick={() => setEditing(null)}>
              {t('common.cancel')}
            </button>
          </div>
        </section>
      )}

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
                  {/* уровень называется словом: от него зависит, что можно
                      сделать, а по одному виду строки этого не понять */}
                  {topic.level !== 'system' && (
                    <span className="hint"> · {t(`bank.levels.${topic.level}`)}</span>
                  )}
                  {topic.may_edit && (
                    <>
                      <button
                        type="button"
                        className="link"
                        onClick={() =>
                          setEditing({
                            id: topic.id,
                            title: topic.title,
                            expression: topic.expression?.all
                              ? topic.expression
                              : { all: topic.expression && Object.keys(topic.expression).length ? [topic.expression] : [] },
                            parent: topic.parent,
                          })
                        }
                      >
                        {t('common.edit')}
                      </button>
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        onClick={() => run(deleteTopic(topic.id))}
                      >
                        ✕
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-head spread">
              <h2>{found ? found.title : t('common.loading')}</h2>
              {found?.needs_course && (
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



            <ul className="problem-list">
              {(found ? found.problems : []).map((problem) => (
                <li key={problem.id}>
                  <Pick id={problem.id} picked={picked} onChange={setPicked} />
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
                {found.needs_course
                  ? t('bank.topics.nothingYet')
                  : t('bank.topics.nothing')}
              </p>
            )}
          </section>
        </div>
      )}
    </main>
  )
}
