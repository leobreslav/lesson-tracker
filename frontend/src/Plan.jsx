import {
  Suspense,
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
import PlanDiff from './PlanDiff'
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
import Switch from './Switch'
import { lastChoice, rememberChoice } from './remember'
import { lazyChunk } from './lazyChunk'
import {
  afterClick,
  applyMove,
  countBlocks,
  planRows,
  selectableIds,
} from './planLogic'
import {
  createPlanNode,
  splitPlan,
  deleteTemplate,
  fetchSubjects,
  fetchTemplate,
  fetchTemplates,
  importTemplate,
  updateTemplate,
  publishPlan,
  refreshTemplate,
  deletePlanNode,
  deletePlanNodes,
  downloadPlan,
  fetchCourses,
  fetchReviews,
  fetchPlan,
  fetchBaseline,
  fetchPlanSlots,
  submitBaseline,
  fetchSchoolYears,
  importPlanFile,
  importPlanRows,
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
const LessonPanel = lazyChunk(() => import('./LessonPanel'))

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
  const [comparing, setComparing] = useState(false)
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
  const [adding, setAdding] = useState(null) // {parent, after, is_section, title}
  const [deleting, setDeleting] = useState(null) // the section being removed
  /*
   * Выбор строк пачкой.
   *
   * Десять уроков подряд удалялись десятью нажатиями, и каждое звало
   * нативное окно подтверждения — то есть уводило курсор к верху экрана и
   * обратно. Пачка отвечает на это не ускорением того же самого, а другой
   * операцией: выбрали, спросили один раз, удалили одной транзакцией.
   *
   * `selecting` — режим, а не постоянная колонка флажков: таблицу читают
   * куда чаще, чем правят, и сорок флажков в ней были бы шумом. `picked`
   * лежит массивом в порядке ленты — по нему считают и «выбрано N», и
   * цену, и порядок этот совпадает с тем, что на экране. `anchor` —
   * прошлое нажатие, от него Shift тянет диапазон.
   */
  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState([])
  const [anchor, setAnchor] = useState(null)
  const [dropping, setDropping] = useState(null) // подтверждение удаления пачки
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

  /*
   * Escape выходит из режима выбора.
   *
   * Тот же жест, что закрывает форму добавления, и слушает он так же
   * документ: курсор в это время ходит по строкам, а не по кнопкам, и
   * целиться в «Отмена» ради отказа от начатого — лишнее движение.
   *
   * Пока открыт вопрос об удалении, Escape принадлежит ему: окно закроется
   * само, а режим при этом уцелеет — иначе один жест делал бы два дела.
   */
  useEffect(() => {
    if (!selecting || dropping) return undefined

    const escape = (event) => {
      if (event.key === 'Escape') stopSelecting()
    }

    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [selecting, dropping])

  /*
   * Смена курса выключает выбор.
   *
   * Строки чужого плана среди выбранного — состояние, которого не бывает:
   * `chosen` пересекается с лентой и вычистил бы их сам, но полоса
   * «выбрано 0» над чужой таблицей всё равно осталась бы висеть, и
   * человек не понял бы, что он там выбирал.
   */
  useEffect(() => {
    setSelecting(false)
    setPicked([])
    setAnchor(null)
  }, [classId])

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

  /**
   * Any structural edit: do it and re-read the whole tree.
   *
   * Ответ сервера возвращается наружу (при отказе — `undefined`): форме
   * добавления нужен id только что созданной строки, чтобы переехать за
   * неё, а не закрыться.
   */
  const run = async (request) => {
    setBusy(true)
    setError(null)

    try {
      const answer = await request()
      await load(classId)
      return answer
    } catch (err) {
      handleError(err)
      return undefined
    } finally {
      setBusy(false)
    }
  }

  /*
   * Что сейчас можно выбрать, и что из выбранного ещё живо.
   *
   * Дерево перечитывается после каждой правки, и строка, выбранная до неё,
   * могла уехать: её удалил импорт, её унесла тема. Поэтому выбранное
   * пересекается с лентой на каждом рендере, а не чинится эффектом —
   * состояние тогда одно, и разъезжаться нечему.
   */
  const order = useMemo(() => selectableIds(data?.nodes ?? []), [data])
  const chosen = useMemo(() => {
    const alive = new Set(order)
    return picked.filter((id) => alive.has(id))
  }, [picked, order])

  const pickedSet = useMemo(() => new Set(chosen), [chosen])

  /**
   * Цена пачки — из уже загруженного дерева, без запроса.
   *
   * Дерево возит `has_content` и число вложений у каждой строки (само
   * содержание едет отдельным запросом на урок), так что сказать «из них
   * три с содержанием» можно до нажатия и не спрашивая сервер.
   */
  const price = useMemo(() => {
    const wanted = new Set(chosen)
    let content = 0
    let attachments = 0

    const look = (node) => {
      if (!wanted.has(node.id)) return
      if (node.has_content) content += 1
      attachments += node.attachments ?? 0
    }

    for (const node of data?.nodes ?? []) {
      look(node)
      for (const child of node.children ?? []) look(child)
    }

    return { content, attachments }
  }, [chosen, data])

  /** Нажали на флажок: Shift тянет диапазон от прошлого нажатия. */
  const pick = (id, { range = false } = {}) => {
    setPicked(afterClick(chosen, order, id, { anchor, range }))
    setAnchor(id)
  }

  const stopSelecting = () => {
    setSelecting(false)
    setPicked([])
    setAnchor(null)
  }

  const removePicked = async () => {
    const ids = chosen
    setDropping(null)
    await run(() => deletePlanNodes(classId, ids))
    stopSelecting()
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

  /**
   * Курс по умолчанию — из всего, что человеку доступно, а не только из своего.
   *
   * Выбор шёл по списку **своих** курсов, и методист, который сам ничего не
   * ведёт, не получал ничего: `classId` оставался пустым, а страница
   * показывала «сначала заведите курс». Присланный на подпись план при этом
   * лежал в двух кликах и не был виден ни на одном экране — то есть
   * утверждение просто не работало для человека, который только утверждает.
   *
   * Ждущий подписи идёт вперёд своих: методист заходит сюда ради него, а
   * свои курсы он открывает по прошлому выбору, который стоит выше.
   */
  useEffect(() => {
    if (classes === null) return

    setClassId((current) => {
      const known = (id) => Boolean(id) && pickable.some((item) => item.id === id)
      if (known(current)) return current

      const remembered = lastChoice('course')
      if (known(remembered)) return remembered

      return classes[0]?.id ?? waiting[0]?.id ?? pickable[0]?.id ?? null
    })
    // намеренно по спискам, а не по их содержимому: пересобирать выбор на
    // каждое перечитывание дерева незачем
  }, [classes, supervised])

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
    setComparing(false)
    rememberChoice('course', id)
  }

  const classLabel = (item) => {
    const year = yearById.get(item.year)
    return years.length > 1 && year ? `${item.name} · ${year.name}` : item.name
  }

  // --- adding ---

  const openAdd = (options) => {
    setEditing(null)
    setAdding({
      title: '',
      parent: null,
      after: null,
      // «первым уроком темы»: строка встаёт перед нынешним первым, а не в
      // конец блока. У пустой темы вставать не перед чем — тогда просто в неё
      before: null,
      is_section: false,
      // вид строки задан открывшей кнопкой, и спрашивать его незачем: так у
      // «Добавить урок» и «Добавить тему» в панели, у «+» в шапке темы (тема
      // в тему не кладётся) и у клика по свободному слоту
      fixedKind: false,
      ...options,
    })
  }

  /**
   * Ввод подряд: форма остаётся открытой, что бы её ни открыло.
   *
   * Раньше «вставить после» закрывалась, а «добавить в конец» — нет, и
   * снаружи это выглядело как две разные формы: один плюсик оставляет поле,
   * соседний убирает. Причина у закрытия была настоящая — второй урок
   * встал бы **перед** первым, — но лечится она не закрытием, а переездом:
   * якорем становится только что созданная строка, и уроки идут по
   * порядку, как при вводе в конец уровня.
   *
   * Закрывают форму три вещи: Escape, «Закрыть» и «Готово» — то есть
   * человек, а не результат его же действия.
   */
  const submitAdd = async (event, { close = false } = {}) => {
    event.preventDefault()
    const { title, parent, after, before, is_section } = adding
    if (!title.trim()) return

    // разрез темы «после этой строки» — дело разовое: продолжать в нём
    // нечем, следующая тема резала бы уже новый хвост
    const once = close || (after && is_section)

    // Поле очищается оптимистично: ввод подряд не должен ждать ответа. У
    // разового действия очищать нечего — форма уходит целиком, но только
    // после успеха: сервер отказывает не абы как («строку сюда ставить
    // нельзя»), и оставлять человека с сообщением об ошибке вместо
    // набранного названия — худшее, что тут можно сделать.
    if (!once) setAdding({ ...adding, title: '' })

    // Тема «после этой строки» — не создание на уровне, а разрез: внутри
    // блока хвост уроков переезжает под новый заголовок, снаружи тема
    // просто встаёт следом. Считает это сервер: где кончается блок и что
    // в него входит, знает он, а не форма.
    const created = await run(() =>
      is_section && after
        ? splitPlan(after, title.trim())
        : createPlanNode({
            course: classId,
            parent,
            after,
            before,
            is_section,
            title: title.trim(),
          }),
    )

    // Отказ: набранное возвращаем в поле, если человек не начал печатать
    // заново. Форма при этом остаётся открытой — в том числе у «Готово».
    if (!created) {
      if (!once)
        setAdding((current) =>
          current && !current.title ? { ...current, title } : current,
        )
      return
    }

    // Форма могла закрыться, пока летел запрос, — тогда и не открываем:
    // функциональная правка видит настоящее состояние, а не снимок.
    if (once) setAdding(null)
    else if (created.id)
      // Форма переезжает **за** созданную строку — всегда, кем бы её ни
      // открыли. Так место формы совпадает с местом, куда встанет следующая
      // строка: первый урок темы вставлялся «перед», а второй должен встать
      // под ним, а не над ним.
      setAdding((current) =>
        current ? { ...current, after: created.id, before: null } : current,
      )
  }

  // --- CSV ---

  const handleImport = async ({ file, rows, mode }) => {
    setImporting(false)
    setBusy(true)
    setError(null)
    setNotice(null)

    try {
      // файл или вставка — дальше всё общее: те же режимы, тот же ответ
      const result = rows
        ? await importPlanRows(classId, rows, mode)
        : await importPlanFile(classId, file, mode)
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

  /*
   * Даты, недели и свободные слоты показываются всегда.
   *
   * Три чекбокса над таблицей это переключали, и держались они на догадке
   * «при наборе плана с нуля даты мешают». Не мешают: у нового курса ленты
   * нет вовсе, и колонок тоже — они появляются вместе с расписанием, то
   * есть ровно тогда, когда начинают что-то значить. А выключенные они
   * прятали ровно то, ради чего таблица и заведена: где план ложится на
   * календарь и сколько часов осталось незанятыми.
   *
   * Единственное настоящее условие осталось одно — есть ли расписание.
   */
  const dated = ribbon.length > 0

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
        {/*
          Всё про утверждение — одной группой в шапке, рядом с тумблером.

          Разъехалось оно было по трём местам: отправка лежала под «⋯»
          вместе с импортом и полкой, состояние — подвальной строкой панели
          управления, а сравнение с эталоном — тумблером здесь. Три
          половины одного разговора, и ни одна не рядом с другой: чтобы
          отправить план, надо было вспомнить, что это под многоточием, а
          узнать, дошёл ли он, — посмотреть в другой конец панели.

          Сравнение — не режим таблицы, а другой вид страницы (там есть
          удалённые строки, которых в плане уже нет), поэтому оно и стояло
          в шапке: панель управления в этом виде не показывается вовсе.
          Остальные две половины переехали к нему.
        */}
        {!supervising && (
          <div className="plan-approval">
            {/* состояние утверждения: у плана его нет, оно есть у снимка */}
            {baseline && (baseline.approved || baseline.request) && (
              <span className={`hint approval ${baseline.request?.status ?? 'approved'}`}>
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
              </span>
            )}

            {/* Свой запрос, свой же надзор: решать можно тут, но не вместо
                плана. Ссылка ведёт в тот же экран надзора, каким методист
                смотрит чужие курсы, — второго места для «утвердить» и
                «вернуть» заводить незачем */}
            {selfReview && (
              <span className="hint approval self">
                {t('plan.baseline.youReview')}{' '}
                <button
                  type="button"
                  className="link"
                  onClick={() => setReviewing(true)}
                >
                  {t('plan.baseline.decide')}
                </button>
              </span>
            )}

            <button
              type="button"
              className="secondary"
              disabled={busy || baseline?.request?.status === 'pending'}
              title={t('plan.baseline.hint')}
              onClick={handleSubmitPlan}
            >
              {t('plan.baseline.submit')}
            </button>

            {/* Тумблер, а не кнопка: это выбор из двух видов, и оба надо
                назвать. Кнопка «Сравнить с эталоном» говорила только про
                один из них, а второй, обратный, приходилось искать глазами
                внутри открывшегося экрана — не там, где включали */}
            {baseline?.approved && (
              <Switch
                label={t('plan.diff.switch')}
                value={comparing}
                onChange={setComparing}
                options={[
                  { value: false, label: t('plan.diff.plan') },
                  { value: true, label: t('plan.diff.toggle') },
                ]}
              />
            )}
          </div>
        )}
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
      ) : comparing ? (
        /* страница перерисовывается целиком: ни панели, ни сводки, ни
           таблицы — сравнение показывает и то, чего в плане уже нет */
        <PlanDiff classId={classId} />
      ) : /* Пусто — это когда показать нечего **вообще**: ни своих курсов,
             ни поднадзорных. Условие смотрело только на свои, и методист
             без своих упирался в «заведите курс», хотя ждущий подписи план
             лежал в том же селекте строкой ниже */
      !pickable.length ? (
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
                onClick={() => openAdd({ parent: null, fixedKind: true })}
              >
                {t('plan.addLesson')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => openAdd({ parent: null, is_section: true, fixedKind: true })}
              >
                {t('plan.addSection')}
              </button>

              {/*
                «Выбрать» стоит третьей и вполсилы: включают её реже, чем
                добавляют строки, но чаще, чем лезут в импорт и на полку, —
                а главное, это действие над таблицей целиком, как и обе
                кнопки слева от неё.
              */}
              <button
                type="button"
                className="secondary"
                disabled={busy || !order.length}
                aria-pressed={selecting}
                onClick={() => (selecting ? stopSelecting() : setSelecting(true))}
              >
                {t('plan.select')}
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
                  </div>
                )}
              </div>
            </div>

            {helpOpen && <PlanCsvHelp />}
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
              {/* Пустое состояние — над таблицей, а не под ней: под пустой
                  таблицей объяснение находят, только пролистав пустоту, а
                  кнопки, к которым оно отсылает, стоят наверху */}
              {!data.nodes.length && (
                <EmptyState title={t('plan.empty.title')}>
                  {t('plan.empty.hint')}
                </EmptyState>
              )}

              <PlanTable
                nodes={data.nodes}
                layout={layout}
                blocks={blocks}
                dated={dated}
                busy={busy}
                collapsed={collapsed}
                editing={editing}
                adding={adding}
                spotlight={target.row}
              spotlightSlot={target.slot}
              debts={debtIds}
              selecting={selecting}
              selected={pickedSet}
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
                  pick,
                }}
              />

              {/*
                Полоса выбранного стоит под таблицей и липнет к низу окна:
                выбирают строки где угодно, чаще в середине и в конце, а
                кнопка «Удалить» должна быть под рукой, а не в полутора
                тысячах пикселей выше.
              */}
              {selecting && (
                <div className="selection-bar plan-selection">
                  <span>
                    {chosen.length
                      ? t('plan.picked', {
                          lessons: t('common.lessonCount', { count: chosen.length }),
                        })
                      : t('plan.pickNothing')}
                  </span>
                  <button
                    type="button"
                    disabled={busy || !chosen.length}
                    onClick={() => setDropping(chosen)}
                  >
                    {t('common.delete')}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={stopSelecting}
                  >
                    {t('common.cancel')}
                  </button>
                </div>
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

      {/*
        Один вопрос на всю пачку — и с ценой.

        Прежнее нативное окно называло одно название и ничего больше;
        десять таких окон подряд читать перестают со второго. Здесь
        спрашивают один раз, и в вопросе стоит то, что нельзя вернуть:
        сколько строк с содержанием и сколько с вложениями. Пустые строки
        такой приписки не получают — терять в них нечего, кроме названия.
      */}
      {dropping && (
        <Modal
          onClose={() => setDropping(null)}
          title={t('plan.dropPicked.title', {
            lessons: t('common.lessonCount', { count: dropping.length }),
          })}
        >
          {(price.content > 0 || price.attachments > 0) && (
            <p className="hint">
              {t('plan.dropPicked.cost', {
                content: price.content,
                attachments: price.attachments,
              })}
            </p>
          )}
          <div className="actions">
            <button type="button" disabled={busy} onClick={removePicked}>
              {t('common.delete')}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setDropping(null)}
            >
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
