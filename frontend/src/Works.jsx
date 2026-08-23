import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import CoursePicker from './CoursePicker'
import Markdown from './Markdown'
import ScanWizard from './ScanWizard'
import TaskList from './TaskList'
import WorkDialog from './WorkDialog'
import { iconFor } from './fileKind'
import {
  createWork,
  openAttachment,
  deleteWork,
  fetchCourses,
  fetchTasks,
  fetchWorks,
  updateWork,
} from './api'
import { lastChoice, rememberChoice } from './remember'

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

  /**
   * Работа, к которой уже можно что-то приложить.
   *
   * Файл ложится на строку в базе, а задание пишут в окне создания, где
   * строки ещё нет. Поэтому первый файл (или первая вставленная картинка)
   * заводит работу с тем, что набрано, и окно продолжает править её же —
   * «Сохранить» после этого уже правка, а не создание.
   *
   * `run` здесь не годится: он гасит форму на время запроса, а запрос идёт
   * посреди загрузки файла — и человек смотрел бы на выключенное окно,
   * гадая, что происходит. Ошибку показывает то место, откуда позвали.
   */
  const ensureWork = async (fields) => {
    if (editing.work) return editing.work

    const created = await createWork(fields)
    setEditing({ work: created })
    reload().catch(handleError)
    return created
  }

  const removeWork = (work) => {
    // ответы уходят вместе с работой, поэтому спрашиваем числом, а не «точно?»
    const question = work.tasks_count
      ? t('works.deleteWithTasks', { name: work.title, count: work.tasks_count })
      : t('works.delete', { name: work.title })
    if (!window.confirm(question)) return

    run(() => deleteWork(work.id))
  }

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
        {/* Бланк живёт здесь, а не в мастере разбора. Печатают его раз в год
            пачкой и **до** контрольной; мастер открывают после, со стопкой
            исписанных листов в руках, и ссылка «распечатать» там отвечала на
            вопрос, решённый неделю назад. Работе он при этом не принадлежит —
            бланк единый на все, — поэтому и стоит у списка, а не в строке */}
        <p className="hint">
          <a href="/blank.pdf" target="_blank" rel="noreferrer">
            {t('scan.printBlank')}
          </a>{' '}
          {t('scan.printBlankHint')}
        </p>
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
                    {/* Три действия — одной группой, а не тремя соседями
                        сетки. Порознь они стояли на своих колонках, и зазор
                        между ними был общим зазором строки: тем же, каким
                        отделены стрелка и название. Для текста это в самый
                        раз, а для трёх одинаковых рамок подряд мало —
                        читались они одной полосой с надрезами. Здесь зазор
                        свой и назван от самих кнопок: не меньше их
                        собственных полей, иначе просвет между кнопками уже
                        просвета внутри кнопки, и глаз склеивает их обратно.

                        Не единой панелькой с общей рамкой: общая рамка с
                        чертой внутри в этом приложении уже значит другое —
                        один вопрос и выбор из ответов (`.source-switch`).
                        Здесь же три разных дела: правка настроек, разбор
                        пачки сканов и переход на страницу проверки. */}
                    <div className="work-actions">
                      {/* Правка — страница, а не окно: у работы, которую уже
                          ведут, полей много (задание с картинками, файлы,
                          окно времени, попытки, оценивание), и в окне поверх
                          списка они читались в щёлку. Окно осталось
                          заведению — там три поля, и список из виду терять
                          не хочется.

                          Кнопка одна. Их было две — «Настройки» здесь и
                          «Править задание» под текстом задания, — и
                          отвечали они на один вопрос: как поправить работу.
                          Задание среди её полей самое заметное, так что
                          отдельного входа ему больше не нужно */}
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={busy}
                        onClick={() => navigate(`/works/${work.id}/edit`)}
                      >
                        {t('works.editAction')}
                      </button>

                      {/* Сканы у любой работы. Прежде кнопка была только у
                          бумажной, и это запирало обычный случай: класс писал
                          онлайн, а сдал на бумаге — или учитель завёл работу
                          пустой и принёс пачку. Резать при этом есть что
                          всегда: скан ложится на строку «работа и ученик», а
                          онлайн-ответы живут на отправках и друг другу не
                          мешают */}
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={busy}
                        onClick={() => setScanning(work)}
                      >
                        {t('scan.open')}
                      </button>

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
                    </div>

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
                      {/* Задание — над задачами, и видит его тут учитель, а
                          не только ученик.

                          Прежде текст задания жил ровно в одном месте: в окне
                          настроек, куда заходят, чтобы что-то поправить.
                          Поэтому написанное в нём было не видно ниоткуда, и
                          работа, ведённая без задач (условие текстом, решения
                          фотографиями), выглядела на этом экране пустой —
                          «задач пока нет» и ничего больше. Показывать ученику
                          то, чего не видит учитель, нельзя: они говорят об
                          одном и том же задании и должны видеть одно и то же */}
                      {work.description && (
                        <div className="work-brief">
                          <Markdown text={work.description} />
                        </div>
                      )}

                      {(work.files ?? []).length > 0 && (
                        <ul className="attachments work-files">
                          {work.files.map((item) => (
                            <li key={item.id} className="attachment">
                              <span className="attachment-icon" aria-hidden="true">
                                {iconFor(item)}
                              </span>
                              <button
                                type="button"
                                className="link title"
                                title={t('lesson.download')}
                                onClick={() =>
                                  openAttachment(item.id).catch(handleError)
                                }
                              >
                                {item.title}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}

                      {/* Задачи — тем же списком, что на странице работы,
                          но **на чтение**: заглянуть «что там внутри», не
                          уходя со списка. Правки здесь нет намеренно — два
                          места для одного действия это ровно то, на что
                          жаловались, когда работу правили и кнопкой в
                          строке, и кнопкой под заданием */}
                      <TaskList
                        workId={work.id}
                        tasks={tasks}
                        readOnly
                        onChanged={() => reloadTasks(expanded)}
                      />
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
          /* Перечитываем и на закрытии, не только на «применить». Мастер
             пишет в базу задолго до конца: первым шагом он заводит ячейки
             работы — пятнадцать штук или сколько заказали, — и делает это
             сразу, потому что дальше в них ложатся баллы с бланка. Закрытие
             без перечитывания оставляло на экране прежний список, и работа
             выглядела пустой, хотя ячейки уже были: следующая заведённая
             руками задача получала номер 15 из ниоткуда. Стоит это одного
             запроса — против экрана, который врёт о содержимом базы. */
          onClose={() => {
            setScanning(null)
            run(() => Promise.resolve())
          }}
          onDone={() => reload()}
        />
      )}

      {editing && (
        <WorkDialog
          work={editing.work}
          courseId={courseId}
          busy={busy}
          onSubmit={saveWork}
          onEnsure={ensureWork}
          onClose={() => setEditing(null)}
        />
      )}

    </main>
  )
}
