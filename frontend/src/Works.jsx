import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import Markdown from './Markdown'
import TaskDialog from './TaskDialog'
import WorkDialog from './WorkDialog'
import {
  createTask,
  createWork,
  deleteTask,
  deleteWork,
  fetchCourses,
  fetchTasks,
  fetchWorks,
  moveTask,
  recheckTask,
  updateTask,
  updateWork,
} from './api'
import { dateTime } from './dates'

/**
 * Работы курса: контрольные, проверочные, домашние.
 *
 * Список строками, раскрывается одна — тот же приём, что у курсов в разделе
 * «Школа», и по той же причине: у работы внутри задачи с многострочными
 * условиями, и восемь развёрнутых работ читались бы как одна простыня.
 *
 * Состояние работы приходит с сервера. «Открыта ли» — вопрос о времени, и
 * считать его в браузере значило бы получить работу, которая на экране уже
 * открыта, а на сервере ещё нет: часы у них разные.
 */
export default function Works({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [courses, setCourses] = useState(null)
  const [courseId, setCourseId] = useState(null)
  const [works, setWorks] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [tasks, setTasks] = useState([])
  const [editing, setEditing] = useState(null) // {work} | {work: null}
  const [editingTask, setEditingTask] = useState(null) // {task} | {task: null}
  const [busy, setBusy] = useState(false)
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
        setCourseId((current) => current ?? list[0]?.id ?? null)
      })
      .catch(handleError)
  }, [handleError])

  const reload = useCallback(
    () => (courseId ? fetchWorks(courseId).then(setWorks) : Promise.resolve()),
    [courseId],
  )

  useEffect(() => {
    setWorks(null)
    setExpanded(null)
    reload().catch(handleError)
  }, [reload, handleError])

  const reloadTasks = useCallback(
    (workId) => (workId ? fetchTasks(workId).then(setTasks) : Promise.resolve(setTasks([]))),
    [],
  )

  useEffect(() => {
    reloadTasks(expanded).catch(handleError)
  }, [expanded, reloadTasks, handleError])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await reload()
      await reloadTasks(expanded)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const saveWork = (fields) =>
    run(() =>
      (editing.work ? updateWork(editing.work.id, fields) : createWork(fields)).then(
        () => setEditing(null),
      ),
    )

  const removeWork = (work) => {
    // ответы уходят вместе с работой, поэтому спрашиваем числом, а не «точно?»
    const question = work.tasks_count
      ? t('works.deleteWithTasks', { name: work.title, count: work.tasks_count })
      : t('works.delete', { name: work.title })
    if (!window.confirm(question)) return

    run(() => deleteWork(work.id))
  }

  const saveTask = (fields) =>
    run(() =>
      (editingTask.task
        ? updateTask(editingTask.task.id, fields)
        : createTask({ ...fields, work: expanded })
      ).then(() => setEditingTask(null)),
    )

  const recheck = (task) => run(() => recheckTask(task.id).then(() => setEditingTask(null)))

  if (courses === null) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  if (!courses.length) {
    return (
      <EmptyState
        title={t('works.needCourse.title')}
        actions={
          <button type="button" onClick={() => navigate('/classes')}>
            {t('plan.needClass.action')}
          </button>
        }
      >
        {t('works.needCourse.hint')}
      </EmptyState>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('nav.works')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="year-picker">
        {courses.map((course) => (
          <button
            type="button"
            key={course.id}
            className={course.id === courseId ? 'chip active' : 'chip'}
            onClick={() => setCourseId(course.id)}
          >
            {course.name}
          </button>
        ))}
      </div>

      <section className="panel">
        <div className="panel-head spread">
          <h3>{t('works.title')}</h3>
          <button type="button" disabled={busy} onClick={() => setEditing({ work: null })}>
            {t('works.add')}
          </button>
        </div>
        <p className="hint">{t('works.hint')}</p>

        {works === null ? (
          <p>{t('common.loading')}</p>
        ) : works.length === 0 ? (
          <p className="hint">{t('works.none')}</p>
        ) : (
          <ul className="course-list work-list">
            {works.map((work) => {
              const open = expanded === work.id

              return (
                <li key={work.id} className={open ? 'course-row open' : 'course-row'}>
                  <div className="course-head">
                    <button
                      type="button"
                      className="link toggle"
                      aria-expanded={open}
                      aria-label={t(open ? 'plan.collapse' : 'plan.expand')}
                      onClick={() => setExpanded(open ? null : work.id)}
                    >
                      {open ? '▾' : '▸'}
                    </button>

                    <button
                      type="button"
                      className="link name"
                      disabled={busy}
                      onClick={() => setExpanded(open ? null : work.id)}
                    >
                      {work.title}
                    </button>

                    <span className={`badge state-${work.state}`}>
                      {t(`works.state.${work.state}`)}
                    </span>

                    <span className="hint what">
                      {dateTime(work.opens_at)} — {dateTime(work.closes_at)}
                    </span>

                    <span className="hint">
                      {t('works.taskCount', { count: work.tasks_count })}
                    </span>

                    <button
                      type="button"
                      className="link"
                      aria-label={t('works.delete', { name: work.title })}
                      disabled={busy}
                      onClick={() => removeWork(work)}
                    >
                      ✕
                    </button>
                  </div>

                  {open && (
                    <div className="course-body">
                      <div className="row work-actions">
                        <span className="hint">
                          {work.attempts === null
                            ? t('works.attemptsFree')
                            : t('works.attemptsLimited', { count: work.attempts })}
                          {' · '}
                          {t(work.show_result ? 'works.resultShown' : 'works.resultHidden')}
                        </span>
                        <button
                          type="button"
                          className="secondary compact"
                          disabled={busy}
                          onClick={() => setEditing({ work })}
                        >
                          {t('works.settings')}
                        </button>
                        {/* проверка — своя страница: таблица на тридцать
                            человек в раскрытой строке не помещается */}
                        <button
                          type="button"
                          className="secondary compact"
                          disabled={busy}
                          onClick={() => navigate(`/works/${work.id}`)}
                        >
                          {t('table.open')}
                        </button>
                      </div>

                      {tasks.length === 0 ? (
                        <p className="hint">{t('works.task.none')}</p>
                      ) : (
                        <ol className="task-list">
                          {tasks.map((task, index) => (
                            <li key={task.id}>
                              <div className="task-question">
                                <Markdown text={task.question} />
                              </div>
                              {/* эталоны и кнопки одной строкой: спрятанные
                                  до наведения кнопки не должны оставлять
                                  за собой пустую строку */}
                              <div className="task-line">
                                <div className="answers">
                                  {task.answers.length === 0 ? (
                                    <span className="hint">
                                      {t('works.task.noAnswers')}
                                    </span>
                                  ) : (
                                    task.answers.map((answer, position) => (
                                      <span className="tag" key={position}>
                                        {answer}
                                      </span>
                                    ))
                                  )}
                                </div>
                                <div className="task-actions">
                                <button
                                  type="button"
                                  className="link"
                                  disabled={busy || index === 0}
                                  aria-label={t('plan.up')}
                                  onClick={() => run(() => moveTask(task.id, 'up'))}
                                >
                                  ↑
                                </button>
                                <button
                                  type="button"
                                  className="link"
                                  disabled={busy || index === tasks.length - 1}
                                  aria-label={t('plan.down')}
                                  onClick={() => run(() => moveTask(task.id, 'down'))}
                                >
                                  ↓
                                </button>
                                <button
                                  type="button"
                                  className="link"
                                  disabled={busy}
                                  onClick={() => setEditingTask({ task })}
                                >
                                  {t('common.edit')}
                                </button>
                                <button
                                  type="button"
                                  className="link"
                                  disabled={busy}
                                  aria-label={t('works.task.delete')}
                                  onClick={() =>
                                    window.confirm(t('works.task.deleteConfirm')) &&
                                    run(() => deleteTask(task.id))
                                  }
                                >
                                  ✕
                                </button>
                                </div>
                              </div>
                            </li>
                          ))}
                        </ol>
                      )}

                      <div className="row">
                        <button
                          type="button"
                          className="secondary compact"
                          disabled={busy}
                          onClick={() => setEditingTask({ task: null })}
                        >
                          {t('works.task.add')}
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {editing && (
        <WorkDialog
          work={editing.work}
          courseId={courseId}
          busy={busy}
          onSubmit={saveWork}
          onClose={() => setEditing(null)}
        />
      )}

      {editingTask && (
        <TaskDialog
          task={editingTask.task}
          busy={busy}
          onSubmit={saveTask}
          onRecheck={recheck}
          onClose={() => setEditingTask(null)}
        />
      )}
    </main>
  )
}
