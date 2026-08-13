import {
  Fragment,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCenter,
  pointerWithin,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import EmptyState from './EmptyState'
import ImportDialog from './ImportDialog'
import PlanCsvHelp from './PlanCsvHelp'
import Modal from './Modal'
import { EmptyDropZone, SortableRow, dragId, emptyZoneId } from './PlanDnd'
import { freeSlots, layoutTotals, stitchLayout } from './planLayout'
import { dayMonth, longDate, shortDate, shortWeekday } from './dates'
import { today } from './calendarLogic'
import {
  applyMove,
  countBlocks,
  planRows,
  resolveDropTarget,
} from './planLogic'
import {
  createPlanNode,
  fetchSubjects,
  fetchTemplates,
  importTemplate,
  publishPlan,
  refreshTemplate,
  deletePlanNode,
  downloadPlan,
  fetchCourses,
  fetchPlan,
  fetchBaseline,
  fetchPlanSlots,
  fixBaseline,
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
const FREE_OPEN_KEY = 'planFreeOpen'

// столько свободных слотов показываем сразу: свернуть три строки — значит
// заставить нажать кнопку ради трёх строк
const FREE_INLINE = 5

function remembered(key, fallback) {
  try {
    const saved = localStorage.getItem(key)
    return saved === null ? fallback : saved === '1'
  } catch {
    return fallback
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // приватный режим — просто не запоминаем
  }
}

const rememberedDates = () => remembered(DATES_KEY, true)

// xlsx первым: он и по умолчанию
const FORMATS = ['xlsx', 'csv']

export default function Plan({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  // the screen-reader script for dragging: dnd-kit reads it out on pick-up
  const dndInstructions = { draggable: t('plan.dndInstructions') }
  const [classes, setClasses] = useState(null)
  const [years, setYears] = useState([])
  const [classId, setClassId] = useState(null)
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
  const [freeOpen, setFreeOpen] = useState(() => remembered(FREE_OPEN_KEY, false))
  const [adding, setAdding] = useState(null) // {parent, after, is_section, title}
  const [deleting, setDeleting] = useState(null) // the section being removed
  const [importing, setImporting] = useState(false)
  // the library, only as far as this page needs it: what can be taken, and
  // whether this plan is already on the shelf under my name
  const [dialog, setDialog] = useState(null)
  const [templates, setTemplates] = useState([])
  const [subjects, setSubjects] = useState([])
  const [notice, setNotice] = useState(null)
  const [collapsed, setCollapsed] = useState(() => new Set())

  const [dragged, setDragged] = useState(null) // {node} — what is being dragged
  const [drop, setDrop] = useState(null) // {overId, side, parent, index}
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
      .then((result) => !cancelled && setBaseline(result.created_at))
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

  // --- dragging ---

  const sensors = useSensors(
    // a small mouse shift, otherwise clicking a title would count as a drag
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    // a delay on touch: without it scrolling the list turns into a drag
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 6 },
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  /** Nested droppables: ask what sits under the cursor first. */
  const collisionDetection = useCallback((args) => {
    const withinPointer = pointerWithin(args)
    // keyboard dragging has no cursor — closestCenter answers there
    return withinPointer.length ? withinPointer : closestCenter(args)
  }, [])

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
    const rows = planRows(data?.nodes ?? [])
    return {
      byId: new Map(
        stitchLayout(rows, ribbon, today()).map((row) => [row.id, row]),
      ),
      totals: layoutTotals(rows, ribbon),
      free: freeSlots(rows, ribbon),
    }
  }, [data, ribbon])

  const items = useMemo(() => {
    const map = new Map()

    ;(data?.nodes ?? []).forEach((node, index) => {
      map.set(dragId(node.id), { node, parent: null, index })
      ;(node.children ?? []).forEach((child, childIndex) => {
        map.set(dragId(child.id), { node: child, parent: node.id, index: childIndex })
      })
    })

    return map
  }, [data])

  /** Whether the dragged node sits below the middle of the hovered one. */
  const isBelow = (event) => {
    const active = event.active.rect.current.translated
    const over = event.over?.rect
    if (!active || !over) return false
    return active.top + active.height / 2 > over.top + over.height / 2
  }

  const readTarget = (event) => {
    const overId = event.over?.id
    if (!overId) return null

    const target = resolveDropTarget({
      items,
      activeId: event.active.id,
      overId,
      below: isBelow(event),
    })

    return target && { ...target, overId, side: isBelow(event) ? 'after' : 'before' }
  }

  const handleDragStart = (event) => {
    setEditing(null)
    setDragged(items.get(event.active.id) ?? null)
  }

  const handleDragOver = (event) => setDrop(readTarget(event))

  const handleDragCancel = () => {
    setDragged(null)
    setDrop(null)
  }

  const handleDragEnd = (event) => {
    const target = readTarget(event)
    const node = items.get(event.active.id)?.node
    setDragged(null)
    setDrop(null)

    if (target && node) dropNode(node.id, target.parent, target.index)
  }

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

  const classLabel = (item) => {
    const year = yearById.get(item.year)
    return years.length > 1 && year ? `${item.name} · ${year.name}` : item.name
  }

  const toggleSection = (id) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  // --- editing ---

  /**
   * Renaming, for folders.
   *
   * A lesson is not renamed here: clicking it opens the panel, where the
   * title sits above its content. A folder has no content, so a folder is
   * just a name and an inline field is the shortest way to change it.
   */
  const startEdit = (node) => setEditing({ id: node.id, title: node.title })

  const submitEdit = (event) => {
    event.preventDefault()
    const { id, title } = editing
    setEditing(null)

    if (!title.trim()) return
    run(() => updatePlanNode(id, { title: title.trim() }))
  }

  const editKeyDown = (event) => {
    if (event.key === 'Escape') setEditing(null)
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
   * Зафиксировать план эталоном.
   *
   * Перефиксация спрашивает: снимок один на план, и прежний уйдёт вместе с
   * ответом на вопрос «относительно чего мы считали расхождение».
   */
  const handleBaseline = async () => {
    if (baseline && !window.confirm(t('plan.baseline.confirm'))) return

    setError(null)
    try {
      const saved = await fixBaseline(classId)
      setBaseline(saved.created_at)
      setNotice(t('plan.baseline.done', { count: saved.rows }))
    } catch (err) {
      handleError(err)
    }
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

  const removeSection = (keepChildren) => {
    const section = deleting
    setDeleting(null)
    run(() => deletePlanNode(section.id, keepChildren))
  }

  // --- rendering ---

  const editForm = () => (
    <form className="plan-edit" onSubmit={submitEdit}>
      <input
        autoFocus
        value={editing.title}
        maxLength={200}
        aria-label={t('plan.titleLabel')}
        onChange={(event) => setEditing({ ...editing, title: event.target.value })}
        onKeyDown={editKeyDown}
      />
      <button type="submit" disabled={busy}>
        {t('common.save')}
      </button>
      <button type="button" className="secondary" onClick={() => setEditing(null)}>
        {t('common.cancel')}
      </button>
    </form>
  )

  const addForm = () => (
    <form className="plan-add-form" onSubmit={submitAdd}>
      <input
        autoFocus
        value={adding.title}
        maxLength={200}
        placeholder={t(
          adding.is_section ? 'plan.sectionPlaceholder' : 'plan.lessonPlaceholder',
        )}
        aria-label={t('plan.titleLabel')}
        onChange={(event) => setAdding({ ...adding, title: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setAdding(null)
        }}
      />
      <button type="submit" disabled={busy || !adding.title.trim()}>
        {t('common.add')}
      </button>
      <button type="button" className="secondary" onClick={() => setAdding(null)}>
        {t('plan.done')}
      </button>
    </form>
  )

  const addFormFor = (parent, after) =>
    adding && adding.parent === parent && adding.after === after ? addForm() : null

  const moveButtons = (node, mover) => (
    <>
      <button
        type="button"
        className="link"
        title={t('plan.up')}
        disabled={busy}
        onClick={() => run(() => mover(node.id, 'up'))}
      >
        ↑
      </button>
      <button
        type="button"
        className="link"
        title={t('plan.down')}
        disabled={busy}
        onClick={() => run(() => mover(node.id, 'down'))}
      >
        ↓
      </button>
    </>
  )

  const indicatorFor = (id) => (drop?.overId === dragId(id) ? drop.side : null)

  /** Строка-разделитель: заголовок терма, каникулы или черта «сегодня». */
  const divider = (mark, key) => {
    if (mark.kind === 'term') {
      return (
        <li className="plan-term" key={key}>
          <strong>{mark.name}</strong>
          <span className="hint">
            {shortDate(mark.start)} — {shortDate(mark.end)}
          </span>
        </li>
      )
    }

    if (mark.kind === 'today') {
      return (
        <li className="plan-today" key={key}>
          {t('plan.today')}
        </li>
      )
    }

    return (
      <li className="plan-divider break" key={key}>
        <span>
          {t('plan.breakBetween', {
            title: mark.title,
            start: shortDate(mark.start),
            end: shortDate(mark.end),
          })}
        </span>
      </li>
    )
  }

  // без расписания раскладывать нечего: «не помещается» на каждой строке —
  // это шум, а не сообщение
  const dated = showDates && ribbon.length > 0

  /** Черты вокруг строки урока: каникулы сверху, конец терма снизу. */
  const marks = (node, side) =>
    dated && node
      ? (layout.byId.get(node.id)?.[side] ?? []).map((mark, index) =>
          divider(mark, `${side}-${node.id}-${index}`),
        )
      : null

  /**
   * Левая колонка недели: подпись в первой строке **с датой** и больше
   * ничего — у главы дат нет, и номер недели там смотрелся бы случайным.
   *
   * Саму группу показывает заливка каждой второй недели — линий и рамок
   * тут нет: строк в таблице сорок, и любой декор на них множится.
   */
  const weekCell = (node) => {
    if (!dated) return null
    const week = layout.byId.get(node.id)?.week

    return (
      <span className="plan-weekmark">
        {showWeeks && week?.labelled && t('plan.week', { number: week.number })}
      </span>
    )
  }

  /**
   * Свободные слоты — даты, на которые уроков плана не хватило.
   *
   * Их бывает и восемьдесят: при позиционном сопоставлении они идут хвостом
   * после последнего урока, поэтому по умолчанию свёрнуты в одну строку. До
   * пяти показываем сразу — сворачивать три строки значит требовать нажатия
   * ради трёх строк.
   */
  const renderFree = () => {
    const free = layout.free
    if (!dated || !showFree || !free.length) return null

    const many = free.length > FREE_INLINE
    const open = !many || freeOpen

    return (
      <>
        {many && (
          <button
            type="button"
            className="link free-summary"
            aria-expanded={open}
            onClick={() => {
              setFreeOpen(!freeOpen)
              remember(FREE_OPEN_KEY, !freeOpen)
            }}
          >
            {open ? '▾' : '▸'}{' '}
            {t('plan.freeSummary', {
              count: free.length,
              start: dayMonth(free[0].slot.date),
              end: dayMonth(free.at(-1).slot.date),
            })}
          </button>
        )}

        {open && (
          <ul className="plan free">
            {free.map(({ slot, labelled }) => (
              <li
                key={slot.id}
                className={`plan-row free${slot.week % 2 === 0 ? ' week-even' : ''}`}
              >
                <span className="plan-weekmark">
                  {showWeeks && labelled && t('plan.week', { number: slot.week })}
                </span>
                <span className="plan-date">
                  {dayMonth(slot.date)} <em>{shortWeekday(slot.date)}</em>
                </span>
                {/* ни ручки, ни номера: это не строка плана, а пустое место
                    в расписании */}
                <span />
                <span />
                <span className="plan-title-cell">
                  <button
                    type="button"
                    className="link title free-slot"
                    disabled={busy}
                    onClick={() => openAdd({ parent: null })}
                  >
                    {t('plan.freeSlot')}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </>
    )
  }

  /** Чётные недели закрашены — этим и группируются. */
  const weekStripe = (node) => {
    const week = dated && showWeeks && layout.byId.get(node.id)?.week
    return week && week.number % 2 === 0 ? ' week-even' : ''
  }

  /**
   * Дата и день недели урока — узкая колонка слева.
   *
   * У темы даты нет (её диапазон стоит в полосе), но ячейка нужна пустой:
   * иначе полоса съехала бы влево относительно строк уроков.
   */
  const dateCells = (node, empty = false) => {
    if (!dated) return null
    if (empty) return <span className="plan-date" />
    const slot = layout.byId.get(node.id)?.slot

    return slot ? (
      <span className="plan-date">
        {dayMonth(slot.date)} <em>{shortWeekday(slot.date)}</em>
      </span>
    ) : (
      <span className="plan-date missing">{t('plan.noSlot')}</span>
    )
  }

  const renderLesson = (node, parent) => (
    <SortableRow
      key={node.id}
      id={dragId(node.id)}
      className={
        'plan-row lesson' +
        weekStripe(node) +
        (dated && !layout.byId.get(node.id)?.slot ? ' no-slot' : '') +
        (dated && layout.byId.get(node.id)?.past ? ' past' : '')
      }
      indicator={indicatorFor(node.id)}
    >
      {(handle) => (
        <>
          {/* левая колонка: неделя и дата. Взгляд идёт по левому краю и
              должен встречать данные, а не служебную ручку */}
          {weekCell(node)}
          {dateCells(node)}
          {handle}
          <span className="plan-number">{node.number}</span>
          <span className={parent ? 'plan-title-cell nested' : 'plan-title-cell'}>
            <button
              type="button"
              className="link title"
              title={node.title}
              disabled={busy}
              onClick={() => setOpened(node.id)}
            >
              {node.title}
            </button>

            {/* two separate marks: one says there is a lesson written, the
                other that something comes with it */}
            {node.has_content && (
              <span
                className="mark"
                title={t('plan.hasContent')}
                aria-label={t('plan.hasContent')}
              >
                📝
              </span>
            )}
            {node.attachments > 0 && (
              <span
                className="mark"
                title={t('plan.hasAttachments', { count: node.attachments })}
                aria-label={t('plan.hasAttachments', { count: node.attachments })}
              >
                📎
              </span>
            )}

            {node.note && (
              <span className="hint note" title={node.note}>
                {node.note}
              </span>
            )}
          </span>

          <span className="row-actions">
            {moveButtons(node, movePlanNode)}
            <button
              type="button"
              className="link"
              title={t('plan.insertAfter')}
              disabled={busy}
              onClick={() => openAdd({ parent, after: node.id })}
            >
              +
            </button>
            <button
              type="button"
              className="link"
              title={t('common.delete')}
              disabled={busy}
              onClick={() => removeLesson(node)}
            >
              ✕
            </button>
          </span>
        </>
      )}
    </SortableRow>
  )

  const renderSection = (node) => {
    const hidden = collapsed.has(node.id)
    const childIds = node.children.map((child) => dragId(child.id))
    // the section lights up when a lesson hovers over it as a container
    const isTarget = drop?.parent === node.id

    return (
      <SortableRow
        key={node.id}
        id={dragId(node.id)}
        className={`plan-section${isTarget ? ' drop-inside' : ''}`}
        indicator={indicatorFor(node.id)}
      >
        {(handle) => (
          <>
        <div className={`plan-row section-head${weekStripe(node)}`}>
          {weekCell(node)}
          {dateCells(node, true)}
          {handle}
          {/* треугольник стоит в колонке номера: у главы номера нет, а
              место есть — и свёртка оказывается ровно под номерами */}
          <button
            type="button"
            className="link toggle"
            title={t(hidden ? 'plan.expand' : 'plan.collapse')}
            onClick={() => toggleSection(node.id)}
          >
            {hidden ? '▸' : '▾'}
          </button>

          {editing?.id === node.id ? (
            <span className="plan-title-cell">{editForm()}</span>
          ) : (
            <>
              <span className="plan-title-cell">
                <button
                  type="button"
                  className="link title"
                  title={t('plan.rename')}
                  disabled={busy}
                  onClick={() => startEdit(node)}
                >
                  {node.title}
                </button>
                {/* только число уроков: даты этой главы и так стоят в её
                    строках, а левая колонка — не место для правой зоны */}
                <span className="hint block-count">
                  {t('common.lessonCount', {
                    count: blocks.byId.get(node.id)?.lessons ?? 0,
                  })}
                </span>
              </span>

              <span className="row-actions">
                {moveButtons(node, movePlanSection)}
                <button
                  type="button"
                  className="link"
                  title={t('plan.addToSection')}
                  disabled={busy}
                  onClick={() => openAdd({ parent: node.id })}
                >
                  +
                </button>
                <button
                  type="button"
                  className="link"
                  title={t('plan.deleteSection')}
                  disabled={busy}
                  onClick={() => setDeleting(node)}
                >
                  ✕
                </button>
              </span>
            </>
          )}
        </div>

        {!hidden && (
          <SortableContext items={childIds} strategy={verticalListSortingStrategy}>
            <ul className="plan-children">
              {node.children.map((child, index) => (
                <Fragment key={child.id}>
                  {/* у первого урока черта уже нарисована над полосой темы */}
                  {index > 0 && marks(child, 'before')}
                  {renderLesson(child, node.id)}
                  {addFormFor(node.id, child.id)}
                </Fragment>
              ))}
              {addFormFor(node.id, null)}
              {!node.children.length && (
                <EmptyDropZone
                  sectionId={node.id}
                  active={drop?.overId === emptyZoneId(node.id)}
                />
              )}
            </ul>
          </SortableContext>
        )}
          </>
        )}
      </SortableRow>
    )
  }

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
            <button type="button" onClick={() => navigate('/classes')}>
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
                      onClick={() => navigate('/status')}
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
                      onClick={() => navigate('/status')}
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
              <DndContext
                sensors={sensors}
                collisionDetection={collisionDetection}
                accessibility={{ screenReaderInstructions: dndInstructions }}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragEnd={handleDragEnd}
                onDragCancel={handleDragCancel}
              >
                <SortableContext
                  items={data.nodes.map((node) => dragId(node.id))}
                  strategy={verticalListSortingStrategy}
                >
                  <ul className={dated ? 'plan' : 'plan no-dates'}>
                    {data.nodes.map((node) => (
                      <Fragment key={node.id}>
                        {/* черта, выпавшая на первый урок темы, встаёт над
                            её полосой: внутри блока она читалась бы как
                            часть темы, а это граница между ними */}
                        {marks(node.is_section ? node.children?.[0] : node, 'before')}
                        {node.is_section
                          ? renderSection(node)
                          : renderLesson(node, null)}
                        {addFormFor(null, node.id)}
                      </Fragment>
                    ))}
                    {addFormFor(null, null)}
                  </ul>
                </SortableContext>

                <DragOverlay>
                  {dragged && (
                    <div className="plan-row drag-overlay">
                      <span className="handle">⠿</span>
                      {dragged.node.number && (
                        <span className="plan-number">{dragged.node.number}</span>
                      )}
                      <strong>{dragged.node.title}</strong>
                    </div>
                  )}
                </DragOverlay>
              </DndContext>

              {renderFree()}

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
                    disabled={busy}
                    title={
                      baseline
                        ? t('plan.baseline.fixedAt', { date: shortDate(baseline.slice(0, 10)) })
                        : t('plan.baseline.hint')
                    }
                    onClick={handleBaseline}
                  >
                    {t(baseline ? 'plan.baseline.refix' : 'plan.baseline.fix')}
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
        <UseLibraryDialog
          templates={templates.filter(
            (item) => !course?.subject || item.subject === course.subject,
          )}
          busy={busy}
          onSubmit={({ template, mode }) =>
            run(() => importTemplate({ course: classId, template, mode })).then(() =>
              setDialog(null),
            )
          }
          onClose={() => setDialog(null)}
        />
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
        <Modal onClose={() => setDeleting(null)}>
          <h3>{t('plan.removeSection.title', { title: deleting.title })}</h3>
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


/** Taking a plan off the shelf into this course. */
function UseLibraryDialog({ templates, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [template, setTemplate] = useState(templates[0]?.id ?? null)
  const [mode, setMode] = useState('replace')

  return (
    <Modal onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (template) onSubmit({ template, mode })
        }}
      >
        <h3>{t('plan.importLibrary')}</h3>

        {!templates.length ? (
          <p className="hint">{t('library.empty.hint')}</p>
        ) : (
          <>
            <label>
              {t('library.title')}
              <select
                autoFocus
                value={template ?? ''}
                disabled={busy}
                onChange={(event) => setTemplate(Number(event.target.value))}
              >
                {templates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title} — {item.subject_name}, {item.grade}
                  </option>
                ))}
              </select>
            </label>

            <div className="row">
              <label className="checkbox">
                <input
                  type="radio"
                  name="library-mode"
                  checked={mode === 'replace'}
                  onChange={() => setMode('replace')}
                />
                {t('csv.modeReplace')}
              </label>
              <label className="checkbox">
                <input
                  type="radio"
                  name="library-mode"
                  checked={mode === 'append'}
                  onChange={() => setMode('append')}
                />
                {t('csv.modeAppend')}
              </label>
            </div>

            {mode === 'replace' && <p className="error">{t('csv.replaceWarning')}</p>}
            <p className="hint">{t('library.once')}</p>
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !templates.length}>
            {t('library.use')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
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
  const [subject, setSubject] = useState(course?.subject ?? subjects[0]?.id ?? null)
  const [grade, setGrade] = useState(course?.grade_level ?? '')

  if (existing) {
    return (
      <Modal onClose={onClose}>
        <h3>{t('plan.refreshTemplate')}</h3>
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
            onSubmit({ title: title.trim(), description, subject, grade })
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

        <div className="row">
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
          <label>
            {t('library.grade')}
            <input
              type="number"
              min={1}
              max={11}
              value={grade}
              onChange={(event) => setGrade(Number(event.target.value))}
            />
          </label>
        </div>

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
