import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import EmptyState from './EmptyState'
import ImportDialog from './ImportDialog'
import LibraryDialog, { TemplateView } from './LibraryDialog'
import PlanCsvHelp from './PlanCsvHelp'
import PlanTable from './PlanTable'
import { dragId } from './PlanDnd'
import Modal from './Modal'
import { freeSlots, layoutTotals, stitchLayout } from './planLayout'
import { longDate, shortDate } from './dates'
import { today } from './calendarLogic'
import { remember, remembered } from './remember'
import { applyMove, countBlocks, planRows } from './planLogic'
import {
  createPlanNode,
  deleteTemplate,
  fetchSubjects,
  fetchTemplate,
  fetchTemplates,
  importTemplate,
  updateTemplate,
  publishPlan,
  refreshTemplate,
  deletePlanNode,
  downloadPlan,
  fetchCourses,
  fetchPlan,
  fetchBaseline,
  fetchPlanSlots,
  submitBaseline,
  fetchSchoolYears,
  importPlanFile,
  movePlanNode,
  movePlanNodeTo,
  movePlanSection,
  updatePlanNode,
} from './api'

/**
 * Loaded only when a lesson is opened.
 *
 * KaTeX and the Markdown renderer are two thirds of a megabyte, and the plan
 * table needs neither — a teacher who only reorders lessons should never pay
 * for them.
 */
const LessonPanel = lazy(() => import('./LessonPanel'))

// показ дат и недель переживает перезагрузку: при наборе плана с нуля они
// мешают, при планировании нужны, и переключать это каждый раз незачем
const DATES_KEY = 'planShowDates'
const WEEKS_KEY = 'planShowWeeks'
const FREE_KEY = 'planShowFree'

const rememberedDates = () => remembered(DATES_KEY, true)

// xlsx первым: он и по умолчанию
const FORMATS = ['xlsx', 'csv']

export default function Plan({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  /**
   * `?course=&row=` — приход со страницы урока на конкретную строку.
   *
   * Страница урока сама план не правит: подсказанная тема может быть не
   * той, и править её вслепую нельзя. Поэтому оттуда сюда ведёт ссылка, а
   * строку надо не «где-то показать», а найти — на ста уроках это минута
   * поиска глазами.
   *
   * Читается адрес **один раз** и тут же вычищается: после прокрутки
   * параметрам делать нечего, а оставленные, они возили бы к той же
   * строке при каждом «назад» и перезагрузке.
   */
  const [search, setSearch] = useSearchParams()
  const [target] = useState(() => ({
    course: Number(search.get('course')) || null,
    row: Number(search.get('row')) || null,
  }))

  const [classes, setClasses] = useState(null)
  const [years, setYears] = useState([])
  const [classId, setClassId] = useState(target.course)
  const scrolled = useRef(false)
  const [data, setData] = useState(null) // {nodes, counts}

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // {id, title} — folders only
  const [opened, setOpened] = useState(null) // the lesson whose panel is open
  const [helpOpen, setHelpOpen] = useState(false) // справка о формате
  // xlsx по умолчанию: в нём нет ни кодировки, ни разделителя, ни кавычек,
  // то есть ровно тех трёх вещей, на которых спотыкается CSV
  const [format, setFormat] = useState('xlsx')
  const [ribbon, setRibbon] = useState([])
  const [baseline, setBaseline] = useState(null)
  const [showDates, setShowDates] = useState(rememberedDates)
  const [showWeeks, setShowWeeks] = useState(() => remembered(WEEKS_KEY, true))
  const [showFree, setShowFree] = useState(() => remembered(FREE_KEY, true))
  const [adding, setAdding] = useState(null) // {parent, after, is_section, title}
  const [deleting, setDeleting] = useState(null) // the section being removed
  const [importing, setImporting] = useState(false)
  // the library, only as far as this page needs it: what can be taken, and
  // whether this plan is already on the shelf under my name
  const [dialog, setDialog] = useState(null)
  const [templates, setTemplates] = useState([])
  // шаблон, раскрытый на просмотр: его строки приезжают отдельным запросом
  const [preview, setPreview] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [notice, setNotice] = useState(null)
  // свёрнутые темы живут здесь, а не в таблице: при смене курса таблица
  // размонтируется, и свёрнутое иначе разворачивалось бы само
  const [collapsed, setCollapsed] = useState(() => new Set())
  // nodes whose move the server has not confirmed: a repeat drop is ignored
  const pending = useRef(new Set())

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    if (search.toString()) setSearch({}, { replace: true })
  }, [search, setSearch])

  /**
   * Прокрутка к строке — один раз за приход.
   *
   * Дерево перечитывается после каждой правки, и эффект без сторожа
   * возвращал бы человека к той же строке, что бы он ни делал дальше.
   */
  useEffect(() => {
    if (!target.row || !data || scrolled.current) return
    const row = document.querySelector(`[data-node="${dragId(target.row)}"]`)
    if (!row) return
    scrolled.current = true
    row.scrollIntoView({ block: 'center' })
  }, [target.row, data])

  useEffect(() => {
    let cancelled = false

    Promise.all([fetchCourses(), fetchSchoolYears()])
      .then(([classList, yearList]) => {
        if (cancelled) return
        setClasses(classList)
        setYears(yearList)
        setClassId((current) => current ?? classList[0]?.id ?? null)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  const load = useCallback(
    (id) => fetchPlan(id).then(setData),
    [],
  )

  /**
   * Лента слотов курса — вторая половина раскладки.
   *
   * Берётся один раз на курс: от правок плана она не зависит, а сшивка
   * идёт на клиенте, поэтому даты сдвигаются в тот же миг, без запроса.
   */
  useEffect(() => {
    if (!classId) {
      setRibbon([])
      return undefined
    }

    let cancelled = false
    fetchPlanSlots(classId)
      .then((result) => !cancelled && setRibbon(result.slots))
      .catch(() => !cancelled && setRibbon([]))
    fetchBaseline(classId)
      .then((result) => !cancelled && setBaseline(result))
      .catch(() => !cancelled && setBaseline(null))

    return () => {
      cancelled = true
    }
  }, [classId])

  useEffect(() => {
    if (!classId) {
      setData(null)
      return undefined
    }

    let cancelled = false
    setData(null)
    setError(null)

    load(classId).catch((err) => {
      if (!cancelled) handleError(err)
    })

    return () => {
      cancelled = true
    }
  }, [classId, load, handleError])

  /** Any structural edit: do it and re-read the whole tree. */
  const run = async (request) => {
    setBusy(true)
    setError(null)

    try {
      await request()
      await load(classId)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /** Block counters come from the tree already loaded, with no requests. */
  const blocks = useMemo(
    () => countBlocks(planRows(data?.nodes ?? [])),
    [data],
  )

  /**
   * Даты, границы термов и сводка — пересчитываются на каждый рендер.
   *
   * Это и есть смысл задачи: добавили урок — строки ниже съехали, а конец
   * четверти пришёлся на другую строку. Пересчёт стоит один проход по
   * плану, поэтому ни дебаунса, ни запроса здесь не нужно.
   */
  const layout = useMemo(() => {
    // сшивка одна на всё: и строки таблицы, и сводка, и хвост свободных
    // слотов — это разные взгляды на один проход, а не три расчёта
    const stitched = stitchLayout(planRows(data?.nodes ?? []), ribbon, today())

    return {
      byId: new Map(stitched.map((row) => [row.id, row])),
      totals: layoutTotals(stitched, ribbon),
      free: freeSlots(stitched, ribbon),
    }
  }, [data, ribbon])

  /**
   * One request per finished drag.
   *
   * The tree is rebuilt at once and the buttons stay live: another node can
   * be dragged while the request is in flight. A repeat drop of the same node
   * is ignored, or the server would get two moves from one starting state.
   */
  const dropNode = async (nodeId, parent, index) => {
    if (pending.current.has(nodeId)) return

    const snapshot = data
    setError(null)
    setData(applyMove(data, nodeId, parent, index))
    pending.current.add(nodeId)

    try {
      await movePlanNodeTo(nodeId, parent, index)
    } catch (err) {
      setData(snapshot)
      handleError(err)
    } finally {
      pending.current.delete(nodeId)
      // re-read only once every move has settled
      if (!pending.current.size) load(classId).catch(handleError)
    }
  }

  const yearById = useMemo(
    () => new Map(years.map((year) => [year.id, year])),
    [years],
  )

  /**
   * My own shelf entries and the subjects, for the two library buttons.
   *
   * Loaded once: the list is short and the page needs it only to decide
   * between «publish» and «refresh», and to fill the import dialog.
   */
  useEffect(() => {
    Promise.all([fetchTemplates(), fetchSubjects()])
      .then(([shelf, list]) => {
        setTemplates(shelf)
        setSubjects(list)
      })
      .catch(() => {
        // the library is an extra here: a failure must not break the plan
      })
  }, [])

  const course = useMemo(
    () => classes?.find((item) => item.id === classId) ?? null,
    [classes, classId],
  )

  const loadShelf = useCallback(
    () => fetchTemplates().then(setTemplates).catch(() => {}),
    [],
  )

  /**
   * Опубликовать черновик или снять с публикации.
   *
   * Единственное место, где это делается: `from-plan` кладёт шаблон на полку
   * черновиком, и без этой кнопки он остался бы виден одному автору.
   */
  const publishTemplate = (template, published) =>
    run(() => updateTemplate(template.id, { is_published: published })).then(loadShelf)

  const removeTemplate = (template) => {
    if (!window.confirm(t('library.deleteConfirm', { title: template.title }))) return
    setPreview(null)
    run(() => deleteTemplate(template.id)).then(loadShelf)
  }

  const takeTemplate = ({ template, mode }) =>
    run(() => importTemplate({ course: classId, template, mode })).then(() => {
      setDialog(null)
      setPreview(null)
    })

  /** A template of mine matching this course's subject and grade, if any. */
  const mineOnShelf = useMemo(() => {
    if (!course?.subject) return null
    return (
      templates.find(
        (item) =>
          item.mine &&
          item.subject === course.subject &&
          // the shelf stores the year of study, the course points at the
          // school's name for it — «MYP 4» and 9 are the same year
          item.grade === course.grade_level,
      ) ?? null
    )
  }, [templates, course])

  const toggleSection = (id) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const classLabel = (item) => {
    const year = yearById.get(item.year)
    return years.length > 1 && year ? `${item.name} · ${year.name}` : item.name
  }

  // --- adding ---

  const openAdd = (options) => {
    setEditing(null)
    setAdding({ title: '', parent: null, after: null, is_section: false, ...options })
  }

  const submitAdd = async (event) => {
    event.preventDefault()
    const { title, parent, after, is_section } = adding
    if (!title.trim()) return

    // an "insert after" form closes, otherwise the next node would land
    // before the one just created
    if (after) setAdding(null)
    else setAdding({ ...adding, title: '' })

    await run(() =>
      createPlanNode({
        course: classId,
        parent,
        after,
        is_section,
        title: title.trim(),
      }),
    )
  }

  // --- CSV ---

  const handleImport = async ({ file, mode }) => {
    setImporting(false)
    setBusy(true)
    setError(null)
    setNotice(null)

    try {
      const result = await importPlanFile(classId, file, mode)
      await load(classId)
      setNotice(
        (mode === 'sync'
          ? t('plan.synced', {
              created: result.created,
              updated: result.updated,
              deleted: result.deleted,
            })
          : t('plan.imported', {
              rows: result.created_rows,
              sections: result.created_headers,
              lessons: result.created_lessons,
            })),
      )
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /**
   * Отправить план на утверждение.
   *
   * Снимок снимается на сервере в этот же момент: методист смотрит то, что
   * ему прислали, а не то, что учитель успел поправить, пока тот читал.
   * Методиста выбирают, только если их несколько.
   */
  const sendForApproval = async (reviewer) => {
    setError(null)
    setDialog(null)

    try {
      const saved = await submitBaseline(classId, reviewer)
      setBaseline(saved)
      setNotice(
        t('plan.baseline.sent', { name: saved.request.reviewer?.name ?? '' }),
      )
    } catch (err) {
      handleError(err)
    }
  }

  const handleSubmitPlan = () => {
    const people = baseline?.methodists ?? []
    // список методистов у страницы уже есть, поэтому отказ показываем сами:
    // спрашивать сервер, чтобы получить 400, здесь незачем
    if (!people.length) {
      return setError(
        t('errors.no_methodist', {
          subject: baseline?.subject ?? course?.name ?? '',
        }),
      )
    }
    if (people.length > 1) return setDialog({ type: 'reviewer' })
    sendForApproval(people[0].id)
  }

  const handleExport = async () => {
    setError(null)
    try {
      await downloadPlan(classId, format)
    } catch (err) {
      handleError(err)
    }
  }

  // --- deleting ---

  const removeLesson = (node) => {
    if (!window.confirm(t('plan.deleteConfirm', { title: node.title }))) return
    run(() => deletePlanNode(node.id, true))
  }

  /**
   * Шаг вверх или вниз. Какой эндпоинт звать, решает страница: у главы он
   * свой, и таблице про api знать незачем — она только говорит, что нажали.
   */
  const handleMove = (nodeId, direction, isSection) =>
    run(() => (isSection ? movePlanSection : movePlanNode)(nodeId, direction))

  const removeSection = (keepChildren) => {
    const section = deleting
    setDeleting(null)
    run(() => deletePlanNode(section.id, keepChildren))
  }

  // --- rendering ---

  const submitEdit = (event) => {
    event.preventDefault()
    const { id, title } = editing
    setEditing(null)

    if (!title.trim()) return
    run(() => updatePlanNode(id, { title: title.trim() }))
  }

  // без расписания раскладывать нечего: «не помещается» на каждой строке —
  // это шум, а не сообщение
  const dated = showDates && ribbon.length > 0

  if (classes === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('plan.title')}</h1>
      </header>

      {!classes.length ? (
        <EmptyState
          title={t('plan.needClass.title')}
          actions={
            <button type="button" onClick={() => navigate('/school/courses')}>
              {t('plan.needClass.action')}
            </button>
          }
        >
          {t('plan.needClass.hint')}
        </EmptyState>
      ) : (
        <>
          <div className="year-picker">
            {classes.map((item) => (
              <button
                type="button"
                key={item.id}
                className={item.id === classId ? 'chip active' : 'chip'}
                onClick={() => setClassId(item.id)}
              >
                {classLabel(item)}
              </button>
            ))}
          </div>

          {data && (
            <div className="cards plan-cards">
              {ribbon.length > 0 && (
                <>
                  <section className="panel card-stat" data-card="slots">
                    <h2>{layout.totals.slots}</h2>
                    <p className="hint">{t('plan.summary.slots')}</p>
                  </section>
                  <section className="panel card-stat" data-card="lessons">
                    <h2>{layout.totals.lessons}</h2>
                    <p className="hint">{t('plan.summary.lessons')}</p>
                  </section>
                  <section
                    data-card="balance"
                    className={`panel card-stat ${
                      layout.totals.balance < 0 ? 'bad' : 'good'
                    }`}
                  >
                    <h2>
                      {layout.totals.balance > 0 ? '+' : ''}
                      {layout.totals.balance}
                    </h2>
                    <p className="hint">{t('plan.summary.balance')}</p>
                  </section>
                  <section className="panel card-stat" data-card="last">
                    <h2 className="small">
                      {layout.totals.lastDate
                        ? longDate(layout.totals.lastDate)
                        : '—'}
                    </h2>
                    <p className="hint">
                      {t(
                        layout.totals.lastDate
                          ? 'plan.summary.last'
                          : 'plan.summary.doesNotFit',
                      )}
                    </p>
                  </section>

                  {/* эти две ведут на «Раскладку»: там видно, какие именно
                      дни остались пустыми и какие уроки не влезли */}
                  {layout.totals.balance > 0 && (
                    <button
                      type="button"
                      data-card="free"
                      className="panel card-stat link-card"
                      onClick={() => navigate('/')}
                    >
                      <h2>{layout.totals.balance}</h2>
                      <p className="hint">{t('plan.summary.free')}</p>
                    </button>
                  )}
                  {layout.totals.missing > 0 && (
                    <button
                      type="button"
                      data-card="missing"
                      className="panel card-stat bad link-card"
                      onClick={() => navigate('/')}
                    >
                      <h2>{layout.totals.missing}</h2>
                      <p className="hint">{t('plan.summary.missing')}</p>
                    </button>
                  )}
                </>
              )}

              {ribbon.length === 0 && (
                <>
                  <section className="panel card-stat" data-card="lessons">
                    <h2>{data.counts.lessons}</h2>
                    <p className="hint">{t('plan.summary.lessons')}</p>
                  </section>
                  <section className="panel card-stat" data-card="sections">
                    <h2>{data.counts.sections}</h2>
                    <p className="hint">{t('plan.summary.sections')}</p>
                  </section>
                </>
              )}
            </div>
          )}

          {ribbon.length > 0 && (
            <div className="dates-toggle">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showDates}
                  onChange={(event) => {
                    setShowDates(event.target.checked)
                    remember(DATES_KEY, event.target.checked)
                  }}
                />
                {t('plan.summary.dates')}
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showWeeks}
                  onChange={(event) => {
                    setShowWeeks(event.target.checked)
                    remember(WEEKS_KEY, event.target.checked)
                  }}
                />
                {t('plan.summary.weeks')}
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showFree}
                  onChange={(event) => {
                    setShowFree(event.target.checked)
                    remember(FREE_KEY, event.target.checked)
                  }}
                />
                {t('plan.summary.freeSlots')}
              </label>
            </div>
          )}

          {/* состояние утверждения: у плана его нет, оно есть у снимка */}
          {baseline && (baseline.approved || baseline.request) && (
            <p className={`hint approval ${baseline.request?.status ?? 'approved'}`}>
              {baseline.request?.status === 'pending' &&
                t('plan.baseline.pending', {
                  name: baseline.request.reviewer?.name ?? '',
                })}
              {baseline.request?.status === 'returned' && (
                <>
                  {t('plan.baseline.returned', {
                    name: baseline.request.reviewer?.name ?? '',
                  })}{' '}
                  <b>{baseline.request.comment}</b>
                </>
              )}
              {!baseline.request &&
                baseline.approved &&
                t(
                  baseline.approved.self_approved
                    ? 'plan.baseline.approvedSelf'
                    : 'plan.baseline.approved',
                  {
                    date: shortDate(baseline.approved.approved_at.slice(0, 10)),
                    name: baseline.approved.reviewer?.name ?? '',
                  },
                )}
            </p>
          )}

          {/* уроки вне тем — не число сводки, а замечание о структуре */}
          {data && blocks.loose > 0 && (
            <p className="hint plan-loose">
              {t('plan.loose', { count: blocks.loose })}
            </p>
          )}

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="hint" role="status">
              {notice}
            </p>
          )}

          {!data ? (
            <p>{t('common.loading')}</p>
          ) : (
            <>
              <PlanTable
                nodes={data.nodes}
                layout={layout}
                blocks={blocks}
                dated={dated}
                showWeeks={showWeeks}
                showFree={showFree}
                busy={busy}
                collapsed={collapsed}
                editing={editing}
                adding={adding}
                spotlight={target.row}
                // всё, что таблица умеет попросить у страницы, — одним
                // списком: сама она в базу не ходит
                actions={{
                  toggleSection,
                  changeEditing: setEditing,
                  submitEdit,
                  changeAdding: setAdding,
                  add: openAdd,
                  submitAdd,
                  openLesson: setOpened,
                  removeLesson,
                  removeSection: setDeleting,
                  move: handleMove,
                  moveTo: dropNode,
                }}
              />

              {!data.nodes.length && (
                <EmptyState title={t('plan.empty.title')}>
                  {t('plan.empty.hint')}
                </EmptyState>
              )}

              <section className="panel">
                <h3>{t('plan.addTitle')}</h3>
                <div className="actions wrap">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => openAdd({ parent: null })}
                  >
                    {t('plan.addLesson')}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => openAdd({ parent: null, is_section: true })}
                  >
                    {t('plan.addSection')}
                  </button>
                </div>
              </section>

              <section className="panel">
                <div className="panel-head">
                  <h3>{t('plan.transferTitle')}</h3>
                  {/* справка о формате — обычное состояние, а не спрятанная
                      разметка: свёрнутого текста в DOM быть не должно */}
                  <button
                    type="button"
                    className="help-toggle"
                    aria-expanded={helpOpen}
                    aria-label={t('plan.csvHelp.toggle')}
                    title={t('plan.csvHelp.toggle')}
                    onClick={() => setHelpOpen(!helpOpen)}
                  >
                    ?
                  </button>
                </div>

                <div className="actions wrap">
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => setImporting(true)}
                  >
                    {t('plan.importFile')}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={handleExport}
                  >
                    {t('plan.exportFile')}
                  </button>
                  {/* формат нужен только выгрузке: у загруженного файла его
                      называет он сам, по расширению */}
                  <span
                    className="format-switch"
                    role="group"
                    aria-label={t('plan.exportFormat')}
                  >
                    {FORMATS.map((name) => (
                      <button
                        key={name}
                        type="button"
                        className={name === format ? 'chip active' : 'chip'}
                        aria-pressed={name === format}
                        onClick={() => setFormat(name)}
                      >
                        {name}
                      </button>
                    ))}
                  </span>

                  <span className="actions-divider" aria-hidden="true" />

                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => setDialog({ type: 'library' })}
                  >
                    {t('plan.importLibrary')}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => setDialog({ type: 'publish' })}
                  >
                    {t(mineOnShelf ? 'plan.refreshTemplate' : 'plan.publish')}
                  </button>

                  <span className="actions-divider" aria-hidden="true" />

                  <button
                    type="button"
                    className="secondary"
                    disabled={busy || baseline?.request?.status === 'pending'}
                    title={t('plan.baseline.hint')}
                    onClick={handleSubmitPlan}
                  >
                    {t('plan.baseline.submit')}
                  </button>
                </div>

                {helpOpen && <PlanCsvHelp />}
              </section>
            </>
          )}
        </>
      )}

      {opened && (
        <Suspense fallback={null}>
          <LessonPanel
            nodeId={opened}
            onClose={() => setOpened(null)}
            // the marks in the table come from the tree, so a save has to be
            // followed by a re-read — the paperclip appears the moment a file does
            onSaved={() => load(classId).catch(handleError)}
          />
        </Suspense>
      )}

      {importing && (
        <ImportDialog
          classId={classId}
          busy={busy}
          onSubmit={handleImport}
          onClose={() => setImporting(false)}
        />
      )}

      {dialog?.type === 'library' && (
        <LibraryDialog
          templates={templates}
          busy={busy}
          onTake={takeTemplate}
          onOpen={(item) =>
            fetchTemplate(item.id).then(setPreview).catch(handleError)
          }
          onPublish={publishTemplate}
          onDelete={removeTemplate}
          onClose={() => setDialog(null)}
        />
      )}

      {preview && (
        <TemplateView
          template={preview}
          busy={busy}
          onUse={() => takeTemplate({ template: preview.id, mode: 'replace' })}
          onClose={() => setPreview(null)}
        />
      )}

      {dialog?.type === 'reviewer' && (
        <Modal onClose={() => setDialog(null)} title={t('plan.baseline.chooseTitle')}>
          <p className="hint">{t('plan.baseline.chooseHint')}</p>
          <ul className="people-list">
            {(baseline?.methodists ?? []).map((person) => (
              <li key={person.id}>
                <div className="row">
                  <span>{person.name}</span>
                  <button type="button" onClick={() => sendForApproval(person.id)}>
                    {t('plan.baseline.sendTo')}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <div className="actions">
            <button
              type="button"
              className="secondary"
              onClick={() => setDialog(null)}
            >
              {t('common.cancel')}
            </button>
          </div>
        </Modal>
      )}

      {dialog?.type === 'publish' && (
        <PublishDialog
          course={course}
          subjects={subjects}
          existing={mineOnShelf}
          busy={busy}
          onSubmit={(fields) => {
            const request = mineOnShelf
              ? refreshTemplate(mineOnShelf.id, classId)
              : publishPlan({ course: classId, ...fields })

            setBusy(true)
            request
              .then((template) => {
                setTemplates((current) => [
                  ...current.filter((item) => item.id !== template.id),
                  template,
                ])
                setNotice(t('plan.published', { title: template.title }))
                setDialog(null)
              })
              .catch(handleError)
              .finally(() => setBusy(false))
          }}
          onClose={() => setDialog(null)}
        />
      )}

      {deleting && (
        <Modal
          onClose={() => setDeleting(null)}
          title={t('plan.removeSection.title', { title: deleting.title })}
        >
          <p className="hint">
            {t('plan.removeSection.hint', {
              count: t('common.lessonCount', { count: deleting.children.length }),
            })}
          </p>
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => removeSection(true)}>
              {t('plan.removeSection.keep')}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => removeSection(false)}
            >
              {t('plan.removeSection.withChildren')}
            </button>
            <button type="button" className="secondary" onClick={() => setDeleting(null)}>
              {t('common.cancel')}
            </button>
          </div>
        </Modal>
      )}
    </main>
  )
}


/**
 * Putting this plan on the shelf, or refreshing what is already there.
 *
 * Refreshing asks nothing: the entry already knows its title and subject,
 * and the only question — «take the current plan?» — is the button itself.
 */
function PublishDialog({ course, subjects, existing, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState(
    course ? `${course.subject_name ?? ''} ${course.grade_name ?? ''}`.trim() : '',
  )
  const [description, setDescription] = useState('')
  const [subject, setSubject] = useState(subjects[0]?.id ?? null)
  const [grade, setGrade] = useState('')

  // курс обычно знает и то и другое — тогда не спрашиваем и не отправляем:
  // шаблон снимается с этого курса, и разойтись с ним ему нечем. Спрашиваем
  // только то, чего у курса нет: так бывает у курсов, заведённых до
  // справочников
  const asksSubject = !course?.subject
  const asksGrade = !course?.grade_level

  if (existing) {
    return (
      <Modal onClose={onClose} title={t('plan.refreshTemplate')}>
        <p className="hint">{t('plan.refreshHint', { title: existing.title })}</p>
        <div className="actions">
          <button type="button" disabled={busy} onClick={() => onSubmit({})}>
            {t('plan.refreshTemplate')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (title.trim()) {
            onSubmit({
              title: title.trim(),
              description,
              ...(asksSubject ? { subject } : {}),
              ...(asksGrade ? { grade } : {}),
            })
          }
        }}
      >
        <h3>{t('plan.publish')}</h3>
        <p className="hint">{t('plan.publishHint')}</p>

        <div className="field">
          <label htmlFor="template-title">{t('plan.titleLabel')}</label>
          <input
            id="template-title"
            autoFocus
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>

        {!asksSubject && !asksGrade ? (
          <p className="hint">
            {t('plan.publishFromCourse', {
              subject: course.subject_name,
              grade: course.grade_level,
            })}
          </p>
        ) : (
          <div className="row">
            {asksSubject && (
              <label>
                {t('library.subject')}
                <select
                  value={subject ?? ''}
                  onChange={(event) => setSubject(Number(event.target.value))}
                >
                  {subjects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {asksGrade && (
              <label>
                {t('library.grade')}
                {/* верхней границы нет: одиннадцать лет — местная система, а
                    в британской и IB-школе их тринадцать. То же правило, что
                    у параллелей в справочнике */}
                <input
                  type="number"
                  min={1}
                  value={grade}
                  onChange={(event) => setGrade(Number(event.target.value))}
                />
              </label>
            )}
          </div>
        )}

        <div className="field">
          <label htmlFor="template-note">{t('plan.noteLabel')}</label>
          <input
            id="template-note"
            value={description}
            maxLength={500}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        <div className="actions">
          <button type="submit" disabled={busy || !title.trim()}>
            {t('plan.publish')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
