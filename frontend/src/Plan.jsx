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
import {
  debtSlots,
  freeSlots,
  layoutTotals,
  passedSlots,
  recordedSlots,
  stitchLayout,
} from './planLayout'
import { shortDate } from './dates'
import { today } from './calendarLogic'
import CoursePicker from './CoursePicker'
import { useDismissable } from './UserMenu'
import DebtsDialog from './DebtsDialog'
import Supervision from './Supervision'
import { lastChoice, remember, remembered, rememberChoice } from './remember'
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
  fetchReviews,
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
    // свободный час, к которому нужно дописать строку: приходят сюда со
    // страницы занятия, у которого строки не осталось
    slot: Number(search.get('slot')) || null,
    // `edit=1` — открыть окно правки сразу: со страницы занятия сюда
    // приходят именно за ним, и «мы вас привели, теперь нажмите» это ещё
    // одно нажатие ради того, о чём уже попросили
    edit: search.get('edit') === '1',
    // куда вернуться, закрыв окно. Принимается только адрес занятия: в
    // параметр можно написать что угодно, и «навигация по присланной
    // строке» — это открытый редирект, даже когда он внутренний
    back: /^\/lesson\/\d+$/.test(search.get('back') || '')
      ? search.get('back')
      : null,
  }))

  const [classes, setClasses] = useState(null)
  // чужие планы под надзором: у методиста они лежат в том же селекте, в
  // своих группах. Не методист — пустой список, и групп в селекте нет
  const [supervised, setSupervised] = useState([])
  const [years, setYears] = useState([])
  const [classId, setClassId] = useState(target.course)
  const scrolled = useRef(false)
  const panelOpened = useRef(false)
  const [data, setData] = useState(null) // {nodes, counts}

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // {id, title} — folders only
  const [opened, setOpened] = useState(null) // the lesson whose panel is open
  const [menuOpen, setMenuOpen] = useState(false)
  // свой курс под собственным надзором: решение принимается по просьбе, а
  // не вместо плана — иначе своего плана не видно вовсе
  const [reviewing, setReviewing] = useState(false)
  const menuRef = useDismissable(menuOpen, () => setMenuOpen(false))
  const [debts, setDebts] = useState(false) // открыт ли разбор долгов
  // адрес, откуда пришли за правкой: закрытие окна возвращает туда, а не
  // оставляет в плане, который человек и не собирался открывать
  const [returnTo, setReturnTo] = useState(null)
  const [helpOpen, setHelpOpen] = useState(false) // справка о формате
  // xlsx по умолчанию: в нём нет ни кодировки, ни разделителя, ни кавычек,
  // то есть ровно тех трёх вещей, на которых спотыкается CSV
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
   * Окно правки — как только пришло дерево.
   *
   * От разметки не зависит намеренно: строка появляется в ней не в тот же
   * миг, и ждать её незачем — панели нужен только id.
   *
   * Сторож одноразовый: без него окно возвращалось бы после каждого
   * закрытия, пока дерево перечитывается.
   */
  useEffect(() => {
    if (!target.row || !target.edit || !data || panelOpened.current) return
    panelOpened.current = true
    setOpened(target.row)
    setReturnTo(target.back)
  }, [target, data])

  /**
   * Прокрутка к строке — один раз за приход.
   *
   * **Зависимостей у эффекта нет вовсе, и это не небрежность.** Строка
   * появляется в разметке не тогда, когда приходит дерево, а на один-два
   * рендера позже; эффект, зависевший от `data`, промахивался мимо неё и
   * больше не повторялся — прокрутка молча не случалась примерно в половине
   * случаев. Сторож стоит на ref, поэтому лишние проходы бесплатны.
   */
  useEffect(() => {
    if (scrolled.current) return
    const anchor = target.row
      ? `[data-node="${dragId(target.row)}"]`
      : target.slot
        ? `[data-slot="${target.slot}"]`
        : null
    if (!anchor) return

    const row = document.querySelector(anchor)
    if (!row) return
    scrolled.current = true
    row.scrollIntoView({ block: 'center' })
  })

  useEffect(() => {
    let cancelled = false

    fetchReviews()
      .then((answer) => !cancelled && setSupervised(answer.plans))
      .catch(() => !cancelled && setSupervised([]))

    Promise.all([fetchCourses(), fetchSchoolYears()])
      .then(([classList, yearList]) => {
        if (cancelled) return
        setClasses(classList)
        setYears(yearList)
        // порядок: адрес, на который привели, потом прошлый выбор, потом
        // первый попавшийся — иначе учитель с пятнадцатью курсами каждый
        // заход начинал бы с первого по алфавиту
        setClassId((current) => {
          const remembered = lastChoice('course')
          const known = (id) => classList.some((item) => item.id === id)
          if (current && known(current)) return current
          if (known(remembered)) return remembered
          return classList[0]?.id ?? null
        })
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
    // чужой курс под надзором своего плана нам не отдаст — и правильно: у
    // методиста прав на него нет, спрашивать значило бы ловить 404 в консоль
    if (!classId || !(classes ?? []).some((item) => item.id === classId)) {
      setRibbon([])
      setBaseline(null)
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
  }, [classId, classes])

  useEffect(() => {
    // то же, что с лентой: чужой план запрашивать нечем и незачем
    if (!classId || !(classes ?? []).some((item) => item.id === classId)) {
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
  }, [classId, classes, load, handleError])

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
      // прошедшие часы без записи: их видно строкой в таблице, а не только
      // счётчиком — час стоит в окружении, с датой, темой и соседями
      debts: debtSlots(ribbon, today()),
      // записанные — рядом с долгами и той же лентой: одно без другого не
      // читается
      recorded: recordedSlots(ribbon),
      // прошедшие часы: пока их нет, год не начался и учёт показывать нечем
      passed: passedSlots(ribbon, today()),
    }
  }, [data, ribbon])

  const debtIds = useMemo(
    () => new Set(layout.debts.map((slot) => slot.id)),
    [layout.debts],
  )

  /** Узел по id: дерево двухуровневое, и плоского вида у него нет. */
  const nodeById = useMemo(() => {
    const map = new Map()
    for (const node of data?.nodes ?? []) {
      map.set(node.id, node)
      for (const child of node.children ?? []) map.set(child.id, child)
    }
    return map
  }, [data])

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

  /**
   * Что лежит в селекте: свои курсы и чужие под надзором.
   *
   * Групп три, потому что это три разные роли человека, а не три свойства
   * курса: свои он ведёт, присланные должен утвердить или вернуть, за
   * остальными смотрит. Пока надзирать нечего, групп нет вовсе — один
   * плоский список, как было.
   */
  const waiting = supervised.filter((row) => row.review?.status === 'pending')
  const watched = supervised.filter((row) => row.review?.status !== 'pending')
  const asCourse = (row) => ({ id: row.id, name: row.name, year: row.year })

  /**
   * Свой курс — свой, даже если методист у него я же.
   *
   * Самоутверждение законно, и в школе, где предмет ведёт один человек, оно
   * обычное дело: тот же учитель значится и методистом. Списки при этом
   * пересекаются, и страница выбирала надзор — то есть человек открывал
   * «Учебный план» и не видел собственного плана вовсе, только плашки
   * чужими глазами. Мой курс поэтому вычитается из поднадзорных, и в
   * селекте он стоит один раз.
   */
  const mineIds = new Set((classes ?? []).map((item) => item.id))
  const others = supervised.filter((row) => !mineIds.has(row.id))
  const otherWaiting = others.filter((row) => row.review?.status === 'pending')
  const otherWatched = others.filter((row) => row.review?.status !== 'pending')

  const pickable = [
    ...(classes ?? []),
    ...others.map(asCourse),
  ]

  const groups = others.length
    ? [
        { key: 'mine', items: classes ?? [] },
        { key: 'waiting', items: otherWaiting.map(asCourse) },
        { key: 'supervised', items: otherWatched.map(asCourse) },
      ].filter((group) => group.items.length)
    : []

  const supervisedRow = supervised.find((row) => row.id === classId) ?? null

  /**
   * Строка надзора для выбранного курса — или `null`, если курс свой.
   *
   * Со своим курсом надзор всё же нужен, и ровно в одном случае: я его
   * методист, и на нём висит мой же запрос. Тогда решение принимается по
   * ссылке из строки состояния — переносить сюда «утвердить» и «вернуть»
   * значило бы завести им второе место жительства.
   */
  const supervising =
    supervisedRow && (!mineIds.has(classId) || reviewing) ? supervisedRow : null

  /** Мой курс, мой запрос, и подписать его могу я сам. */
  const selfReview =
    mineIds.has(classId) && supervisedRow?.review?.status === 'pending'
      ? supervisedRow
      : null

  /** Выбор курса запоминается: он один на все страницы, см. `remember.js`. */
  const pickClass = (id) => {
    setClassId(id)
    setReviewing(false)
    rememberChoice('course', id)
  }

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
      // очередь надзора могла измениться этим же нажатием: если методист
      // курса — я сам, запрос попал ко мне, и решать его отсюда же
      fetchReviews()
        .then((answer) => setSupervised(answer.plans))
        .catch(() => {})
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

  const handleExport = async (chosen) => {
    setError(null)
    try {
      await downloadPlan(classId, chosen)
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
  /**
   * Шаг вверх или вниз. Какой эндпоинт звать, решает страница: у главы он
   * свой, и таблице про api знать незачем — она только говорит, что нажали.
   *
   * Курсор за строкой не бежит и страница под него не подъезжает: было и
   * такое — окно прокручивалось ровно на то, на сколько уехала строка, — но
   * работало это только там, где прокрутке есть куда ехать. Выше нуля не
   * прокрутишь, а на коротком плане прокрутки нет вовсе, то есть в самом
   * нужном случае помощи не было. Теперь попадать никуда не надо: после
   * первого нажатия стрелки отрываются от списка (`.plan-held` в таблице).
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
        {/* курс — в строке заголовка: это не фильтр к странице, а то, про
            что она. Полтора десятка чипов под заголовком занимали две
            строки ради выбора, который делают раз за заход */}
        <CoursePicker
          courses={pickable}
          value={classId}
          onChange={pickClass}
          label={classLabel}
          groups={groups}
        />
      </header>

      {/* чужой план под надзором: числа те же, что видит учитель у себя, и
          считает их тот же код. Правки тут нет никакой — только утвердить
          или вернуть с замечанием */}
      {supervising ? (
        <Supervision
          row={supervising}
          busy={busy}
          onError={handleError}
          onDone={() => {
            // решили — возвращаемся к своему плану, если это был он
            setReviewing(false)
            fetchReviews()
              .then((answer) => setSupervised(answer.plans))
              .catch(handleError)
            // состояние утверждения на своей странице меняется тем же
            // решением, поэтому перечитывается и оно — но только у своего
            // курса: чужой `CourseScopedViewSet` не отдаст, и в консоль
            // упал бы 404 на ровном месте
            if (mineIds.has(classId)) {
              fetchBaseline(classId)
                .then(setBaseline)
                .catch(() => setBaseline(null))
            }
          }}
        />
      ) : !classes.length ? (
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
          {data && (
            <div className="cards plan-cards">
              {ribbon.length > 0 && (
                <>
                  {/* Два числа в одной плашке, двумя равными строками: это
                      два измерения одного и того же — сколько курс идёт и
                      сколько в нём написано, — и порознь ни одно из них ни о
                      чём не говорит. Рядом стоящие карточки предлагали читать
                      их как три независимых показателя, хотя третий и есть
                      разность первых двух. Приём не новый: так же собрана
                      плашка «начали / прошли целиком» в сводке работы. */}
                  <section className="panel card-stat pairs">
                    <p className="pair" data-card="slots">
                      <b>{layout.totals.slots}</b>
                      <span>{t('plan.summary.slots')}</span>
                    </p>
                    <p className="pair" data-card="lessons">
                      <b>{layout.totals.lessons}</b>
                      <span>{t('plan.summary.lessons')}</span>
                    </p>
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
                  {/*
                    Плашек было пять, а разных чисел в них три.

                    «Свободные слоты» показывали ровно баланс, только без
                    знака: +39 и 39 стояли рядом. Дата последнего урока
                    отвечала на вопрос, который в таблице виден строкой —
                    последняя строка плана несёт свою дату. «Не помещается»
                    держалась дольше всех и ушла следом: строки, которым
                    слота не хватило, подсвечены в самой таблице и говорят
                    это словами, а число над ней повторяло их счётом.

                    Осталось третье — долги. Числом они стоят здесь, потому
                    что это статистика курса, а не замечание о нём: строкой
                    в подвале панели «не отмечено занятий: 1» читалось как
                    сноска, хотя это единственное, что требует действия.
                  */}
                  {/* Две строки одной плашки, как слоты и уроки слева:
                      «два не отмечено» — беда при двух записанных и мелочь
                      при сотне, порознь эти числа ничего не значат.

                      Значки те же, что в таблице, и стоят они тут заодно
                      легендой: зелёная галочка — записан, красная точка —
                      долг. Отдельная строка легенды под сводкой объясняла
                      бы то же самое, только не там, где на значки смотрят */}
                  {layout.passed.length > 0 && (
                    <section data-card="records" className="panel card-stat pairs marked">
                      <p className="pair" data-card="recorded">
                        <span className="plan-state recorded" aria-hidden="true">
                          ✓
                        </span>
                        <b>{layout.recorded.length}</b>
                        {/* число и подпись врозь, а склонение общее: подпись
                            знает про count, но его не печатает */}
                        <span>
                          {t('plan.summary.recorded', { count: layout.recorded.length })}
                        </span>
                      </p>
                      {/* Учёт не начат — вторая строка говорит не «0 не
                          отмечено», а сколько часов прошло. Ноль был бы
                          неправдой по существу: занятия прошли, просто
                          долгами они не считаются, пока учитель не начал
                          (иначе первое же нажатие потребовало бы закрыть
                          полгода). Нажатие ведёт на первый прошедший час —
                          там и стоит кнопка «так и было» */}
                      {layout.recorded.length === 0 ? (
                        <p className="pair" data-card="not-started">
                          <span className="plan-state unclosed" aria-hidden="true">
                            •
                          </span>
                          <button
                            type="button"
                            className="link"
                            title={t('plan.summary.startRecording')}
                            onClick={() => navigate(`/lesson/${layout.passed[0].id}`)}
                          >
                            <b>{layout.passed.length}</b>
                          </button>
                          <span>
                            {t('plan.summary.notStarted', {
                              count: layout.passed.length,
                            })}
                          </span>
                        </p>
                      ) : (
                        <p className="pair" data-card="debts">
                          <span className="plan-state unclosed" aria-hidden="true">
                            •
                          </span>
                          {layout.debts.length > 0 ? (
                            <button
                              type="button"
                              className="link"
                              title={t('status.closeDebts')}
                              onClick={() => setDebts(true)}
                            >
                              <b>{layout.debts.length}</b>
                            </button>
                          ) : (
                            <b>{layout.debts.length}</b>
                          )}
                          <span>
                            {t('plan.debtsLabel', { count: layout.debts.length })}
                          </span>
                        </p>
                      )}
                    </section>
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

          {/*
            Одна панель управления над таблицей — всё, что делают с планом
            целиком.

            Кнопки жили в двух карточках **под** таблицей: «Добавить» и
            «Импорт и экспорт», каждая со своим заголовком. На плане в сорок
            уроков это полторы тысячи пикселей прокрутки до кнопки «+ урок»,
            и обе карточки при этом отвечали на вопрос «что сделать с
            планом» — то есть на тот же, что и чекбоксы показа, стоявшие
            наверху. Заголовки у них были подписями к очевидному: два ряда
            кнопок объясняют себя сами.

            Внутри панели три строки, и каждая своя: ряд действий (справа
            прижаты чекбоксы показа), развёрнутая справка о формате и
            строка состояния — утверждение, долги, уроки вне тем. Последняя
            появляется, только когда есть что сказать: пустая занимала бы
            высоту ряда молча.
          */}
          <section className="panel plan-tools">
            <div className="actions wrap">
              {/*
                Два действия и меню — вместо восьми кнопок в ряд.

                Восемь одинаковых прямоугольников с одним словом на каждом
                читались как россыпь, а не как панель: глазу не за что
                зацепиться, и «+ урок» терялся среди «Из библиотеки» и
                «На утверждение». Между тем часто нажимают ровно первые
                две кнопки, а обмен файлами, полку и отправку на
                утверждение — раз в четверть.

                Приём тот же, что на странице занятия: редкое живёт под
                «⋯», частое стоит на виду.
              */}
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

              <div className="plan-menu" ref={menuRef}>
                <button
                  type="button"
                  className="link more"
                  aria-haspopup="true"
                  aria-expanded={menuOpen}
                  aria-label={t('plan.more')}
                  title={t('plan.more')}
                  onClick={() => setMenuOpen(!menuOpen)}
                >
                  ⋯
                </button>
                {menuOpen && (
                  <div className="dropdown">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setMenuOpen(false)
                        setImporting(true)
                      }}
                    >
                      {t('plan.importFile')}
                    </button>
                    {/* формат называет пункт меню: у выгрузки он вопрос
                        «во что», а не настройка, которую держат включённой */}
                    {FORMATS.map((name) => (
                      <button
                        key={name}
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setMenuOpen(false)
                          handleExport(name)
                        }}
                      >
                        {t('plan.exportAs', { format: name })}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false)
                        setHelpOpen(!helpOpen)
                      }}
                    >
                      {t('plan.csvHelp.toggle')}
                    </button>

                    <span className="dropdown-sep" aria-hidden="true" />

                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setMenuOpen(false)
                        setDialog({ type: 'library' })
                      }}
                    >
                      {t('plan.importLibrary')}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setMenuOpen(false)
                        setDialog({ type: 'publish' })
                      }}
                    >
                      {t(mineOnShelf ? 'plan.refreshTemplate' : 'plan.publish')}
                    </button>

                    <span className="dropdown-sep" aria-hidden="true" />

                    <button
                      type="button"
                      disabled={busy || baseline?.request?.status === 'pending'}
                      title={t('plan.baseline.hint')}
                      onClick={() => {
                        setMenuOpen(false)
                        handleSubmitPlan()
                      }}
                    >
                      {t('plan.baseline.submit')}
                    </button>
                  </div>
                )}
              </div>

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
            </div>

            {helpOpen && <PlanCsvHelp />}

            {(baseline?.approved ||
              baseline?.request ||
              selfReview ||
              blocks.loose > 0) && (
              <div className="plan-bar">
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

            {/* Свой запрос, свой же надзор: решать можно тут, но не вместо
                плана. Ссылка ведёт в тот же экран надзора, каким методист
                смотрит чужие курсы, — второго места для «утвердить» и
                «вернуть» заводить не за чем */}
            {selfReview && (
              <p className="hint approval self">
                {t('plan.baseline.youReview')}{' '}
                <button type="button" className="link" onClick={() => setReviewing(true)}>
                  {t('plan.baseline.decide')}
                </button>
              </p>
            )}

            {/* уроки вне тем — не число сводки, а замечание о структуре */}
            {data && blocks.loose > 0 && (
              <p className="hint plan-loose">
                {t('plan.loose', { count: blocks.loose })}
              </p>
            )}
              </div>
            )}
          </section>

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
              spotlightSlot={target.slot}
              debts={debtIds}
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

            </>
          )}
        </>
      )}

      {debts && (
        <DebtsDialog
          courseId={classId}
          onDone={() => {
            setDebts(false)
            // лента перечитывается: закрытые часы перестают быть долгами,
            // а записанные связи меняют раскладку
            fetchPlanSlots(classId)
              .then((result) => setRibbon(result.slots))
              .catch(handleError)
          }}
          onClose={() => setDebts(false)}
        />
      )}

      {opened && (
        <Suspense fallback={null}>
          <LessonPanel
            nodeId={opened}
            // номер и признак «проведено» — из дерева, дата — из сшивки с
            // лентой слотов; знает и то и другое только страница
            where={{
              number: nodeById.get(opened)?.number ?? null,
              // чей это план: окно открывается и со страницы занятия, где
              // курс назван, и из таблицы, где он выбран чипом, — а в самом
              // окне до сих пор не был назван нигде
              course: course?.name ?? null,
              taught: Boolean(nodeById.get(opened)?.taught),
              date: layout.byId.get(opened)?.slot?.date ?? null,
            }}
            onClose={() => {
              setOpened(null)
              if (returnTo) navigate(returnTo)
            }}
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
          {/* Вынуть уроки можно всегда: тема — ярлык, и её снос не трогает
              ни порядок, ни записи. А снести вместе с уроками, среди
              которых есть проведённый, значит оставить прошедший час без
              записи посреди закрытых; сервер это и не даст
              (`plan_delete_taught`), но объяснить надо до нажатия */}
          {deleting.children.some((child) => child.taught) && (
            <p className="hint">{t('plan.removeSection.taught')}</p>
          )}
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => removeSection(true)}>
              {t('plan.removeSection.keep')}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy || deleting.children.some((child) => child.taught)}
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
