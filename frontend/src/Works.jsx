import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import CellDialogBank from './CellDialogBank'
import CoursePicker from './CoursePicker'
import Markdown from './Markdown'
import ScanWizard from './ScanWizard'
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
import { lastChoice, remember, remembered, rememberChoice } from './remember'

// показывать ли эталоны в списке задач: это переключатель вида, а не
// настройка работы, поэтому он помнится браузером, а не хранится в базе
const ANSWERS_KEY = 'worksShowAnswers'

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
  const [editing, setEditing] = useState(null)
  const [scanning, setScanning] = useState(null)
  const [editingTask, setEditingTask] = useState(null) // {task} | {task: null}
  // какой ячейке накатываем условие из банка
  const [takingInto, setTakingInto] = useState(null)
  const [showAnswers, setShowAnswers] = useState(() => remembered(ANSWERS_KEY, false))
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
        // прошлый выбор раньше первого по алфавиту: ключ общий со страницей
        // плана — работают обычно в одном курсе
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

  const pickCourse = (id) => {
    setCourseId(id)
    rememberChoice('course', id)
  }

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

  // пустое состояние — внутри страницы, а не вместо неё: у раздела есть
  // имя, и терять его оттого, что курсов пока нет, незачем
  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('nav.works')}</h1>
        <CoursePicker courses={courses} value={courseId} onChange={pickCourse} />
      </header>

      {!courses.length ? (
        <EmptyState
          title={t('works.needCourse.title')}
          actions={
            <button type="button" onClick={() => navigate('/school/courses')}>
              {t('plan.needClass.action')}
            </button>
          }
        >
          {t('works.needCourse.hint')}
        </EmptyState>
      ) : (
        <>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        <div className="panel-head spread">
          <h3>{t('works.title')}</h3>
          <button type="button" disabled={busy} onClick={() => setEditing({ work: null })}>
            {t('works.add')}
          </button>
        </div>
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

                    {/* в шапке только имя и то, что с работой делают:
                        окно, попытки и число задач — разговор о настройках,
                        и живут они там, где их правят */}
                    {open && tasks.length > 0 && (
                      <button
                        type="button"
                        className={showAnswers ? 'chip active' : 'chip'}
                        aria-pressed={showAnswers}
                        onClick={() => {
                          setShowAnswers(!showAnswers)
                          remember(ANSWERS_KEY, !showAnswers)
                        }}
                      >
                        {t('works.answers')}
                      </button>
                    )}

                    <button
                      type="button"
                      className="secondary compact"
                      disabled={busy}
                      onClick={() => setEditing({ work })}
                    >
                      {t('works.settings')}
                    </button>

                    {/* сканы — только у бумажной: у онлайновой резать нечего,
                        и кнопка, умеющая только отказать, честнее не рисуется */}
                    {work.on_paper && (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={busy}
                        onClick={() => setScanning(work)}
                      >
                        {t('scan.open')}
                      </button>
                    )}

                    {/* проверка — своя страница: таблица на тридцать человек
                        в раскрытой строке не помещается */}
                    <button
                      type="button"
                      className="secondary compact"
                      disabled={busy}
                      onClick={() => navigate(`/works/${work.id}`)}
                    >
                      {t('table.open')}
                    </button>

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
                      {tasks.length === 0 ? (
                        <p className="hint">{t('works.task.none')}</p>
                      ) : (
                        <ol className="task-list">
                          {tasks.map((task, index) => (
                            <li key={task.id}>
                              {/* номер рисуем сами, а не маркером списка:
                                  по нему ищут задачу глазами, и ему нужны
                                  и вес, и своя колонка */}
                              <span className="task-number">{index + 1}.</span>
                              {/* кнопки — в строке условия, а не под ней:
                                  спрятанные до наведения, они иначе держат
                                  за собой пустую строку в каждой задаче */}
                              <div className="task-head">
                                <div className="task-question">
                                  <Markdown text={task.question} />
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
                                {/* заполнить не руками, а готовым условием:
                                    поленились искать — накатили потом */}
                                <button
                                  type="button"
                                  className="link"
                                  disabled={busy}
                                  onClick={() => setTakingInto(task)}
                                >
                                  {t('works.task.bank')}
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

                              {showAnswers && (
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
                              )}
                            </li>
                          ))}
                        </ol>
                      )}

                      {/* «добавить» — последняя строка списка, а не третья
                          кнопка в стороне: добавляют после последней задачи,
                          там ей и место */}
                      <div className="row">
                        <button
                          type="button"
                          className="task-add"
                          disabled={busy}
                          onClick={() => setEditingTask({ task: null })}
                        >
                          + {t('works.task.add')}
                        </button>
                        {/* пустая ячейка — законное состояние: условие на
                            бумаге или на доске, вбивать его незачем. Заполнить
                            её можно потом, руками или из банка */}
                        <button
                          type="button"
                          className="link"
                          disabled={busy}
                          onClick={() => run(() => createTask({ work: work.id }))}
                        >
                          + {t('works.task.blank')}
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
        </>
      )}

      {scanning && (
        <ScanWizard
          work={scanning}
          onClose={() => setScanning(null)}
          onDone={() => reload()}
        />
      )}

      {editing && (
        <WorkDialog
          work={editing.work}
          courseId={courseId}
          busy={busy}
          onSubmit={saveWork}
          onClose={() => setEditing(null)}
        />
      )}

      {takingInto && (
        <CellDialogBank
          task={takingInto}
          answered={
            tasks.find((one) => one.id === takingInto.id)?.answered ?? 0
          }
          onClose={() => setTakingInto(null)}
          onDone={() => {
            setTakingInto(null)
            run(() => Promise.resolve())
          }}
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
