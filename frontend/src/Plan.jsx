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
import { ofCourse, ofTemplate, ownerBody } from './planOwner'
import ImportDialog from './ImportDialog'
import LibraryDialog, { TemplateView } from './LibraryDialog'
import PlanCsvHelp from './PlanCsvHelp'
import PlanTable from './PlanTable'
import PlanDiff, { DiffBody } from './PlanDiff'
import { dragId } from './PlanDnd'
import Modal from './Modal'
import { usePlanLayout } from './usePlanLayout'
import { longDate, shortDate } from './dates'
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
  createTemplate,
  fetchRefreshDiff,
  fetchTakeDiff,
  fetchTemplate,
  fetchTemplates,
  importTemplate,
  updateTemplate,
  keepUpdatingTemplate,
  publishPlan,
  refreshTemplate,
  redoPlan,
  undoPlan,
  deletePlanNode,
  deletePlanNodes,
  downloadPlan,
  fetchCourses,
  fetchReviews,
  fetchPlan,
  fetchPlanHistory,
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

/**
 * Учебный план — курса или шаблона с полки.
 *
 * `template` — номер шаблона; тогда экран открыт **на полке**, и селектора
 * курсов на нём нет: программу пишут для класса, который в этом году не
 * ведут, и курса под неё не существует.
 *
 * Экран при этом **тот же**, а не похожий, и это главное решение всей
 * страницы. Разница между планом курса и планом на полке ровно одна —
 * календарь: у полки нет ни дат, ни расписания, ни утверждения методистом.
 * Всё, что от календаря зависит, страница и так рисует по наличию ленты
 * слотов (`dated`), а у шаблона она пуста по построению — поэтому «вид без
 * дат» тут не второй режим, а то же самое состояние, что у курса, которому
 * ещё не составили расписание.
 */
export default function Plan({ user, onLoggedOut, template = null }) {
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
  // курсы школы: администратор вправе чинить их содержание, и дойти до них
  // ему надо из того же селектора
  const [schoolCourses, setSchoolCourses] = useState([])
  // журнал состояний плана: чем можно отменить и кто правил последним
  const [steps, setSteps] = useState([])
  /*
   * Что сделают кнопки хода — **считает сервер**, а не мы по `steps[0]`.
   *
   * Правило непростое: где план стоит на ленте, что уже пройдено, и чем
   * «Вернуть» называет себя (действием снимка под курсором, а не тем, что
   * оно восстановит). Второй его расчёт здесь был бы зеркалом, которое
   * разъедется молча, — а прежняя кнопка ровно этим и жила: брала самый
   * свежий снимок, и после отмены самым свежим был снимок самой отмены.
   * Наружу это выходило надписью «Отменить: отмену» и планом, который
   * качался между двумя состояниями.
   */
  const [moves, setMoves] = useState({ undo: null, redo: null })
  const [years, setYears] = useState([])
  const [classId, setClassId] = useState(target.course)
  /** Открыты ли мы на полке: у шаблона нет ни курса, ни календаря. */
  const onShelf = Boolean(template)
  /**
   * Чьё дерево правим — зеркало серверного `plans/owning.py`.
   *
   * Источника у него два (адрес шаблона и селектор курсов), а дальше всё
   * одинаково: страница спрашивает дерево, журнал и правки у владельца, не
   * зная, какой он. Пока адресом был номер курса, каждый вызов знал ответ на
   * этот вопрос — и второй владелец означал бы двадцать правок вместо одной.
   */
  const owner = useMemo(
    () => (onShelf ? ofTemplate(template) : classId ? ofCourse(classId) : null),
    [onShelf, template, classId],
  )
  /** Шапка полки: название шаблона вместо селектора курсов. */
  const [shelfCard, setShelfCard] = useState(null)
  /** Окно «переписать план»: что уйдёт, что придёт и чем это подтвердить. */
  const [overwrite, setOverwrite] = useState(null)
  const scrolled = useRef(false)
  const panelOpened = useRef(false)
  const [data, setData] = useState(null) // {nodes, counts}

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // {id, title} — folders only
  const [opened, setOpened] = useState(null) // the lesson whose panel is open
  /*
   * Меню два, и это не дробление ради дробления.
   *
   * Было одно, и в нём под одной чертой лежали две разные темы: обмен
   * файлами («как перенести план в таблицу и обратно») и полка («взять
   * чужой план, отдать свой»). Черта — слабый разделитель: чтобы найти
   * «Из библиотеки», приходилось читать все шесть пунктов. Теперь тема
   * названа на самой кнопке, и читать надо два-три пункта своей.
   */
  const [menuOpen, setMenuOpen] = useState(null) // null | 'file' | 'library'
  const [comparing, setComparing] = useState(false)
  // свой курс под собственным надзором: решение принимается по просьбе, а
  // не вместо плана — иначе своего плана не видно вовсе
  const [reviewing, setReviewing] = useState(false)
  const menuRef = useDismissable(menuOpen !== null, () => setMenuOpen(null))
  const [debts, setDebts] = useState(false) // открыт ли разбор долгов
  // адрес, откуда пришли за правкой: закрытие окна возвращает туда, а не
  // оставляет в плане, который человек и не собирался открывать
  const [returnTo, setReturnTo] = useState(null)
  const [helpOpen, setHelpOpen] = useState(false) // справка о формате
  // «с датами» — уточнение к выгрузке, а не настройка страницы: живёт
  // столько же, сколько открытый экран, и никуда не сохраняется
  const [exportDates, setExportDates] = useState(false)
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
   * Режима «Выбрать» нет: флажок живёт в самой строке и появляется под
   * курсором, как остальные её кнопки, — кнопка на панели была лишним
   * знанием, которое надо было сперва добыть. `picked` лежит массивом в
   * порядке ленты: по нему считают и «выбрано N», и цену, и порядок этот
   * совпадает с тем, что на экране. `anchor` — прошлое нажатие, от него
   * Shift тянет диапазон.
   */
  const [picked, setPicked] = useState([])
  const [anchor, setAnchor] = useState(null)
  const [dropping, setDropping] = useState(null) // подтверждение удаления пачки
  // «понимаю, что теряю» у сноса темы вместе с уроками: спрашивается
  // только когда есть что терять, кроме названий
  const [dropSection, setDropSection] = useState(false)
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

  /**
   * Можно ли **править** план этого курса: свой или, у администратора, любой.
   *
   * Название отвечало на другой вопрос — «чьё содержимое нам отдадут», — и
   * пока правка и чтение совпадали, разницы не было. Теперь чужой план
   * читает вся школа, а правит его по-прежнему автор, и по этому ответу
   * решается ровно одно: идти ли странице за деревом, лентой и эталоном.
   *
   * Считалось это присутствием курса в двух списках — своих и школьных, — и
   * было верно ровно до тех пор, пока школьный список приезжал одному
   * администратору. Теперь его получает каждый учитель (живой план школы
   * читают все), и прежнее условие раздало бы право правки всей школе: не
   * настоящее — сервер откажет, — а показанное. Хуже того, страница пошла бы
   * за деревом, лентой и эталоном чужого курса и уронила бы в консоль три
   * отказа подряд.
   *
   * Поэтому роль спрашивается прямо, как и на сервере: `writable_by` — это
   * ведущий либо администратор школы.
   */
  const mayEdit = useCallback(
    (id) =>
      Boolean(id) &&
      ((classes ?? []).some((item) => item.id === id) ||
        (Boolean(user?.is_school_admin) &&
          schoolCourses.some((item) => item.id === id))),
    [classes, schoolCourses, user],
  )

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

    if (onShelf) {
      // На полке ни курсов, ни надзора нет вовсе, и спрашивать их значило бы
      // ждать три запроса ради селектора, которого на этом экране нет.
      // Пустой список — не заглушка: это и есть ответ «курсов тут не бывает»
      setClasses([])
      setYears([])
      setSupervised([])
      setSchoolCourses([])

      fetchTemplate(template)
        .then((card) => !cancelled && setShelfCard(card))
        .catch((err) => !cancelled && handleError(err))

      return () => {
        cancelled = true
      }
    }

    fetchReviews()
      .then((answer) => !cancelled && setSupervised(answer.plans))
      .catch(() => !cancelled && setSupervised([]))

    Promise.all([fetchCourses(), fetchSchoolYears()])
      .then(([classList, yearList]) => {
        if (cancelled) return
        setClasses(classList)
        setYears(yearList)

        /*
         * Курсы школы — всем, и гейта по роли тут больше нет.
         *
         * Стоял он не из осторожности, а по факту: чужой план отдавался
         * только администратору и назначенному методисту, поэтому у
         * рядового учителя группа «Курсы школы» обещала бы то, чего сервер
         * не даст, — и каждый выбор ронял бы в консоль пару 404. Теперь
         * живой план курса читает вся школа (`plans/approval.readable`), и
         * обещать нечему: чужой открывается на чтение, свой правится как
         * правился.
         *
         * А вот **год тут один — текущий**, и это не про право: читать
         * прошлогодний план школа по-прежнему вправе, ручка отдаёт его как
         * отдавала. Это про то, на какой вопрос отвечает экран.
         *
         * Чужой план открывают ради раскладки: когда у вас производная, на
         * чём вы остановились, успеваете ли до конца четверти. Все три
         * вопроса — про идущий год; у прошлого «остановились» нет вовсе, а
         * даты его сетки отвечают на вопрос, которого никто не задавал.
         * Прошлогодняя программа нужна другим и по-другому — как образец,
         * с которого начинают свой план, — и на это в проекте есть
         * библиотека: снимок на полке, который берут копией.
         *
         * Год берётся тот же, каким его считают «Школа» и школьное
         * расписание, — самый свежий: `SchoolYear` отдаётся упорядоченным
         * по убыванию начала. Второго определения «текущего года» в
         * проекте нет и заводить его тут незачем.
         */
        const current = yearList[0]?.id ?? null

        fetchCourses(current, { scope: 'school' })
          .then((list) => !cancelled && setSchoolCourses(list))
          .catch(() => !cancelled && setSchoolCourses([]))
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError, user, onShelf, template])

  /*
   * Дерево и журнал приезжают вместе.
   *
   * Кнопка отмены обязана называть, что именно отменит, — значит список
   * снимков нужен до нажатия и обязан обновляться в такт с планом. Отдельно
   * их перечитывать нельзя: разъедутся на первой же правке, и кнопка
   * начнёт обещать не то.
   */
  const load = useCallback(
    (id) =>
      Promise.all([fetchPlan(id), fetchPlanHistory(id).catch(() => ({ steps: [] }))])
        .then(([tree, journal]) => {
          setData(tree)
          setSteps(journal.steps)
          setMoves({ undo: journal.undo ?? null, redo: journal.redo ?? null })
        }),
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
    // методиста прав на него нет, спрашивать значило бы ловить 404 в консоль.
    // А вот курс школы администратору отдаст: там право есть.
    //
    // У полки ни ленты, ни эталона нет **вовсе**: она не привязана к
    // учебному году, и спрашивать про её даты не у чего. Пустая лента тут не
    // заглушка, а точный ответ — из неё же следует вид таблицы без дат
    if (onShelf || !mayEdit(classId)) {
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
  }, [classId, mayEdit, onShelf])

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
    if (!picked.length || dropping) return undefined

    const escape = (event) => {
      if (event.key === 'Escape') stopSelecting()
    }

    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [picked, dropping])

  /*
   * Смена курса выключает выбор.
   *
   * Строки чужого плана среди выбранного — состояние, которого не бывает:
   * `chosen` пересекается с лентой и вычистил бы их сам, но полоса
   * «выбрано 0» над чужой таблицей всё равно осталась бы висеть, и
   * человек не понял бы, что он там выбирал.
   */
  useEffect(() => {
    setPicked([])
    setAnchor(null)
  }, [classId])

  useEffect(() => {
    // то же, что с лентой: поднадзорный план запрашивать нечем и незачем.
    // У полки же право спрашивает сервер, и второй его копии тут не будет
    if (!owner || (!onShelf && !mayEdit(classId))) {
      setData(null)
      return undefined
    }

    let cancelled = false
    setData(null)
    setError(null)

    load(owner).catch((err) => {
      if (!cancelled) handleError(err)
    })

    return () => {
      cancelled = true
    }
  }, [owner, onShelf, classId, mayEdit, load, handleError])

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
      await load(owner)
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
  /**
   * Цена удаления — из уже загруженного дерева, без запроса.
   *
   * Дерево возит `has_content` и число вложений у каждой строки (само
   * содержание едет отдельным запросом на урок), так что «из них три с
   * содержанием» можно сказать до нажатия и не спрашивая сервер.
   *
   * Считается по списку id, а не по выбранному: один и тот же расчёт
   * обслуживает и пачку, и одиночный крестик, и снос темы вместе с
   * уроками. Три разных ответа на вопрос «что я сейчас потеряю» разъехались
   * бы молча.
   */
  const priceOf = useCallback(
    (ids) => {
      const wanted = new Set(ids ?? [])
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

      return { content, attachments, lost: content > 0 || attachments > 0 }
    },
    [data],
  )

  /** Нажали на флажок: Shift тянет диапазон от прошлого нажатия. */
  const pick = (id, { range = false } = {}) => {
    setPicked(afterClick(chosen, order, id, { anchor, range }))
    setAnchor(id)
  }

  const stopSelecting = () => {
    setPicked([])
    setAnchor(null)
  }

  /**
   * Удаляется то, что показано в окне, а не то, что выбрано.
   *
   * Раньше здесь стоял `chosen`, и для пачки это было одно и то же — а
   * крестик у строки, пришедший в то же окно, не удалял ничего: выбор при
   * нём пуст. Окно называет цену по `dropping`, значит и удалять обязано
   * его же, иначе спрошено одно, а сделано другое.
   */
  /**
   * Отменить — вернуть план к снимку, снятому перед действием.
   *
   * Без номера отменяется последнее; с номером — конкретный шаг, и это же
   * обслуживает откат чужой правки: снимок вмешательства живёт дольше
   * обычных, и вернуть надо тот, что снят **перед** ним.
   */
  const undo = (snapshot = null) => run(() => undoPlan(owner, snapshot))

  /** Вернуть то, что только что отменили, — шаг вперёд по той же ленте. */
  const redo = () => run(() => redoPlan(owner))

  /** Как называется действие снимка: обеим кнопкам нужно одно и то же. */
  const nameOf = (step) =>
    t(`plan.undo.action.${step.action}`, { defaultValue: step.action })

  /*
   * Чужая правка, с которой ещё ничего не сделали.
   *
   * Учитель узнаёт о ней, только открыв план, — поэтому она названа
   * отдельной строкой, а не спрятана в списке шагов.
   *
   * Пропадает метка сама, и без всякого «прочитано»: ищется она **до
   * первого своего шага**. Сделал что-нибудь — хоть вернул как было, хоть
   * дописал строку рядом — значит план он открыл и правку увидел. Иначе
   * строка висела бы все девяносто дней, что живёт снимок вмешательства, и
   * читаться перестала бы на второй.
   */
  const fresh = []
  for (const step of steps) {
    if (step.mine) break
    fresh.push(step)
  }
  const intervention = fresh.find((step) => !step.by_lead) ?? null

  const removePicked = async () => {
    const ids = dropping ?? []
    setDropping(null)
    await run(() => deletePlanNodes(owner, ids))
    // Режим остаётся включённым: удалили три строки — часто следом идут
    // ещё две, и выходить ради этого, чтобы тут же вернуться, незачем.
    // Выбор при этом сбрасывается: он уже применён.
    setPicked([])
    setAnchor(null)
  }

  /** Block counters come from the tree already loaded, with no requests. */
  const blocks = useMemo(
    () => countBlocks(planRows(data?.nodes ?? [])),
    [data],
  )

  /**
   * Даты, границы термов и сводка — пересчитываются на каждый рендер.
   *
   * Считает их `usePlanLayout` — тот же хук, каким считает свою раскладку
   * экран чужого плана: два прохода по одному плану дали бы две ленты дат,
   * и расходиться они начали бы молча.
   */
  const layout = usePlanLayout(data?.nodes, ribbon)

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
      if (!pending.current.size) load(owner).catch(handleError)
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

  /**
   * Вести дальше этот шаблон, а не прежний.
   *
   * Перечитываем полку целиком, а не правим запись в состоянии: действие
   * трогает **две** записи — пометка снимается с прежнего живого, — и
   * подправив одну, мы показали бы двух живых там, где их не бывает.
   */
  const keepUpdating = (template) =>
    run(() => keepUpdatingTemplate(template.id)).then(loadShelf)

  const removeTemplate = (template) => {
    if (!window.confirm(t('library.deleteConfirm', { title: template.title }))) return
    setPreview(null)
    run(() => deleteTemplate(template.id)).then(loadShelf)
  }

  /**
   * Взять с полки: весь план или выбранные строки.
   *
   * `rows` — конструктор: блок, два блока или один урок. Дальше всё общее,
   * вплоть до ответа, и именно поэтому второго пути тут нет — «взять план»
   * и «взять из плана» отличаются одним полем запроса.
   *
   * Ответ называется словами: без него взятый блок выглядит как ничего не
   * произошедшее — план длинный, дописанное ушло в конец, и на экране
   * ничего не сдвинулось.
   */
  const takeTemplate = ({ template, mode, rows }) => {
    const apply = () =>
      run(() =>
        importTemplate({ course: classId, template, mode, ...(rows ? { rows } : {}) }),
      ).then((result) => {
        setDialog(null)
        setPreview(null)
        setOverwrite(null)
        if (result) {
          setNotice(
            t('plan.imported', {
              rows: result.created_rows,
              sections: result.created_headers,
              lessons: result.created_lessons,
            }),
          )
        }
      })

    /*
     * Спрашиваем ровно там, где есть что терять.
     *
     * «Дописать» ничего не уносит, выбранные строки тоже дописываются, а
     * пустой план терять нечего — во всех трёх случаях лишний вопрос был бы
     * шумом, который приучают проматывать не глядя. А вот «взять целиком»
     * поверх набранного плана стирает его и строит заново, и это
     * единственное действие полки, уносящее чужую работу.
     */
    if (mode !== 'replace' || rows || !data?.nodes.length) return apply()

    return fetchTakeDiff(classId, template)
      .then((diff) =>
        setOverwrite({ what: t('plan.overwrite.take'), diff, apply }),
      )
      .catch(handleError)
  }

  /**
   * Мой **живой** шаблон по предмету и параллели этого курса, если он есть.
   *
   * Раньше здесь стояло «первый мой с тем же предметом», и слово «первый»
   * значило «раньше по алфавиту»: полка приезжает отсортированной по
   * названию. У человека с черновиком и опубликованным по одному предмету
   * «Обновить» молча уходило не туда.
   *
   * Теперь выбирает не порядок списка, а пометка `is_live`, и живой такой
   * один — это держит ограничение базы, а не договорённость.
   */
  const mineOnShelf = useMemo(() => {
    if (!course?.subject) return null
    return (
      templates.find(
        (item) =>
          item.mine &&
          item.is_live &&
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
  /*
   * Учитель и предмет едут с каждым курсом — по ним селект и сужают.
   *
   * Три списка приходят из трёх ответов и называют эти две вещи по-разному:
   * у своего курса ведущие списком (`teachers`), у поднадзорного — один
   * человек объектом, а предмет у первого зовётся `subject_name`, у второго
   * `subject`. Приводится это здесь и один раз: разбираться в трёх формах
   * внутри `CoursePicker` значило бы поселить в нём знание про три ответа
   * сервера.
   *
   * Имя поля — `subjectName`, а не `subject`: у своего курса `subject` это
   * **номер** предмета, и по нему ищется свой шаблон на полке. Положить
   * туда название значило бы сломать поиск молча.
   */
  const asCourse = (row) => ({
    id: row.id,
    name: row.name,
    year: row.year,
    teacher: row.teacher?.name ?? null,
    subjectName: row.subject ?? null,
  })
  const asOwn = (item) => ({
    ...item,
    teacher: item.teachers?.[0]?.name ?? null,
    subjectName: item.subject_name ?? null,
  })

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

  /**
   * Курсы школы — четвёртая группа, и теперь она у всех.
   *
   * Администратор вправе править содержание любого курса своей школы (чинит
   * чужую неделю в расписании ровно так же), а остальные учителя — читать:
   * программа курса общий артефакт школы, а не личная тетрадь. «Мои курсы»
   * от этого не должны распухать — у завуча, ведущего два курса, селектор
   * показал бы девятнадцать, — поэтому право и принадлежность разведены и на
   * клиенте: свои курсы приходят обычным запросом, школьные отдельным.
   */
  const knownIds = new Set([
    ...mineIds,
    ...others.map((row) => row.id),
  ])
  const schoolOnly = schoolCourses.filter((item) => !knownIds.has(item.id))

  /**
   * Два списка, и путать их нельзя: «что можно выбрать» и «что открыть само».
   *
   * Выбрать теперь можно любой курс школы — живой план читают все её
   * учителя. А открываться сам по себе он не должен: у человека, которому
   * ещё не поручили ни одного курса, страница молча уехала бы в чужой план
   * вместо подсказки «заведите курс». Своё, присланное и поднадзорное —
   * дело другое: это его работа, за ней он и пришёл.
   */
  const mineAndWatched = [...(classes ?? []).map(asOwn), ...others.map(asCourse)]
  const pickable = [...mineAndWatched, ...schoolOnly.map(asOwn)]

  const groups =
    others.length || schoolOnly.length
      ? [
          { key: 'mine', items: (classes ?? []).map(asOwn) },
          { key: 'waiting', items: otherWaiting.map(asCourse) },
          { key: 'supervised', items: otherWatched.map(asCourse) },
          { key: 'school', items: schoolOnly.map(asOwn) },
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

      return classes[0]?.id ?? waiting[0]?.id ?? mineAndWatched[0]?.id ?? null
    })
    // намеренно по спискам, а не по их содержимому: пересобирать выбор на
    // каждое перечитывание дерева незачем
  }, [classes, supervised, schoolCourses])

  const supervisedRow = supervised.find((row) => row.id === classId) ?? null

  /**
   * Строка надзора для выбранного курса — или `null`, если курс свой.
   *
   * Со своим курсом надзор всё же нужен, и ровно в одном случае: я его
   * методист, и на нём висит мой же запрос. Тогда решение принимается по
   * ссылке из строки состояния — переносить сюда «утвердить» и «вернуть»
   * значило бы завести им второе место жительства.
   */
  /**
   * Чужой план открывается на чтение, а не пустотой.
   *
   * Веток две, и вторая новая. Курс **под надзором** ведёт себя как вёл:
   * методист смотрит его чужими глазами и решает по запросу. Всякий
   * **другой** чужой курс — тот, который я не веду и не вправе править, —
   * открывается тем же экраном, только без кнопок решения: живой план школы
   * читают все её учителя. Администратор в эту ветку не попадает: он правит
   * содержание любого курса школы, и читать его вместо правки было бы шагом
   * назад.
   *
   * Экрану нужен только id: строку состояния, план и право решать он берёт
   * одним запросом сам.
   */
  const supervising =
    classId &&
    (supervisedRow ? !mineIds.has(classId) || reviewing : !mayEdit(classId))
      ? classId
      : null

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
            ...ownerBody(owner),
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
      await load(owner)
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
      await downloadPlan(classId, chosen, { dates: exportDates })
    } catch (err) {
      handleError(err)
    }
  }

  // --- deleting ---

  /**
   * Крестик у строки — тот же вопрос, что у пачки, и то же окно.
   *
   * Нативным `confirm` это было, и он называл одно название: сколько при
   * этом уходит содержания и вложений, человек не узнавал ни до, ни после.
   * Раз у пачки цена уже считается, второму способу спрашивать про то же
   * самое взяться неоткуда — окно одно, путь один.
   */
  const removeLesson = (node) => setDropping([node.id])

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

  const askRemoveSection = (node) => {
    setDropSection(false)
    setDeleting(node)
  }

  const removeSection = (keepChildren) => {
    const section = deleting
    setDeleting(null)
    run(() => deletePlanNode(section.id, keepChildren))
  }

  // что унесёт «вместе с уроками»: цена считается тем же расчётом, что у
  // пачки и у одиночного крестика
  const sectionPrice = priceOf((deleting?.children ?? []).map((child) => child.id))

  /** Название строки по id — окно удаления одной строки называет её. */
  const titleOf = (id) => {
    for (const node of data?.nodes ?? []) {
      if (node.id === id) return node.title
      for (const child of node.children ?? []) {
        if (child.id === id) return child.title
      }
    }
    return ''
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
        <h1>{onShelf ? t('plan.shelf.title') : t('plan.title')}</h1>
        {/*
          На полке вместо селектора — имя самого шаблона.

          Выбирать тут не из чего: сюда приходят по ссылке на **этот** план,
          а не «в раздел планов». Селектор со всеми своими шаблонами был бы
          вторым списком полки — тем самым, который из проекта убрали, когда
          страницу «Библиотека» заменили окном.
        */}
        {onShelf ? (
          <span className="hint plan-shelf-name">
            {shelfCard?.title ?? ''}
            {shelfCard && !shelfCard.is_published && (
              <> · {t('plan.shelf.draft')}</>
            )}{' '}
            {/* дорога назад — на план: полка открывается оттуда окном, и
                второго её списка в проекте нет намеренно */}
            <button type="button" className="link" onClick={() => navigate('/plan')}>
              {t('plan.shelf.back')}
            </button>
          </span>
        ) : (
          /* курс — в строке заголовка: это не фильтр к странице, а то, про
             что она. Полтора десятка чипов под заголовком занимали две
             строки ради выбора, который делают раз за заход */
          <CoursePicker
            courses={pickable}
            value={classId}
            onChange={pickClass}
            label={classLabel}
            groups={groups}
            /* сужение по учителю и предмету: в этом селекте у любого учителя
               лежат все курсы школы, а их несколько десятков — «найти план
               Петровой по геометрии» иначе значит прочитать весь список */
            narrow="plan"
          />
        )}
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
        {!supervising && !onShelf && (
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

      {/* чужой план: числа те же, что видит учитель у себя, и считает их
          тот же код. Правки тут нет никакой — только прочитать, а у
          методиста ещё и утвердить или вернуть с замечанием */}
      {supervising ? (
        <Supervision
          courseId={supervising}
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
      ) : /* Пусто — это когда **своего** показать нечего: ни своих курсов,
             ни поднадзорных. Условие смотрело только на свои, и методист
             без своих упирался в «заведите курс», хотя ждущий подписи план
             лежал в том же селекте строкой ниже.

             Курсы школы сюда не считаются намеренно: их можно выбрать, но
             своей работы они не заменяют, и человеку, которому ещё не
             поручили курс, надо сказать именно это. Выбрал чужой — ветка
             сюда и не дойдёт, выше стоит `supervising` */
      !onShelf && !mineAndWatched.length ? (
        <EmptyState
          title={t('plan.needClass.title')}
          actions={
            <>
              <button type="button" onClick={() => navigate('/school/courses')}>
                {t('plan.needClass.action')}
              </button>
              {/*
                Второе действие — ровно для того, кто это читает: курса ему не
                поручили, а программу он написать может. Плану на полке курс
                не нужен, и другой двери к нему у человека без курсов нет:
                полка открывается окном с плана, а плана у него ещё нет.
              */}
              <button
                type="button"
                className="secondary"
                onClick={() => setDialog({ type: 'newTemplate' })}
              >
                {t('plan.shelf.create')}
              </button>
            </>
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
              {/*
                Кнопка одна, а вид выбирают в самой форме — тем же тумблером,
                что у «+» на строке. Кнопок было две, и они обещали две разные
                формы там, где форма одна: нажав «Добавить урок», человек уже
                не мог передумать, не закрыв её и не найдя соседнюю.
              */}
              <button
                type="button"
                disabled={busy}
                onClick={() => openAdd({ parent: null })}
              >
                {t('plan.addRow')}
              </button>

              {/*
                Два меню в одной обёртке: клик мимо закрывает открытое, каким
                бы из двух оно ни было.

                На полке их нет, и оба по своей причине. Обмен файлами и
                импорт ходят курсовыми ручками (`?course=`) — открыть их тут
                значило бы нарисовать кнопки, которые ответят отказом. А
                «взять с полки» и «положить на полку», стоя **на** полке,
                отвечают сами на себя: план уже здесь.
              */}
              {!onShelf && (
              <span className="plan-menus" ref={menuRef}>
                <div className="plan-menu">
                  <button
                    type="button"
                    className="secondary"
                    aria-haspopup="true"
                    aria-expanded={menuOpen === 'file'}
                    onClick={() =>
                      setMenuOpen((current) => (current === 'file' ? null : 'file'))
                    }
                  >
                    {t('plan.fileMenu')}
                  </button>
                  {menuOpen === 'file' && (
                    <div className="dropdown">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setMenuOpen(null)
                          setImporting(true)
                        }}
                      >
                        {t('plan.importFile')}
                      </button>
                      <span className="dropdown-sep" />
                      {/* «с датами» стоит над форматами, потому что уточняет
                          их оба: вопрос «во что» и вопрос «с датами ли» —
                          про один и тот же файл. Меню при этом не
                          закрывается: ответив, человек тут же выгружает */}
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={exportDates}
                          onChange={(event) =>
                            setExportDates(event.target.checked)
                          }
                        />
                        {t('plan.exportWithDates')}
                      </label>
                      {/* формат называет пункт меню: у выгрузки он вопрос
                          «во что», а не настройка, которую держат включённой */}
                      {FORMATS.map((name) => (
                        <button
                          key={name}
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setMenuOpen(null)
                            handleExport(name)
                          }}
                        >
                          {t('plan.exportAs', { format: name })}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          setMenuOpen(null)
                          setHelpOpen(!helpOpen)
                        }}
                      >
                        {t('plan.csvHelp.toggle')}
                      </button>
                    </div>
                  )}
                </div>

                <div className="plan-menu">
                  <button
                    type="button"
                    className="secondary"
                    aria-haspopup="true"
                    aria-expanded={menuOpen === 'library'}
                    onClick={() =>
                      setMenuOpen((current) =>
                        current === 'library' ? null : 'library',
                      )
                    }
                  >
                    {t('plan.libraryMenu')}
                  </button>
                  {menuOpen === 'library' && (
                    <div className="dropdown">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setMenuOpen(null)
                          setDialog({ type: 'library' })
                        }}
                      >
                        {t('plan.importLibrary')}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setMenuOpen(null)
                          setDialog({ type: 'publish' })
                        }}
                      >
                        {t(mineOnShelf ? 'plan.refreshTemplate' : 'plan.publish')}
                      </button>
                      {/*
                        «Сохранить копию» стоит только рядом с «Обновить», и
                        это не экономия пункта. Копия — это копия **рядом с
                        ведомым**: пока на полке ничего своего нет, выбор
                        «вести или положить снимком» человеку не о чем
                        задавать, а лишний пункт пришлось бы объяснять.
                      */}
                      {mineOnShelf && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setMenuOpen(null)
                            setDialog({ type: 'publish', copy: true })
                          }}
                        >
                          {t('plan.publishCopy')}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </span>
              )}

              {/*
                «Отменить» появляется, только когда есть что отменять, и
                **называет действие**: безымянная отмена страшнее, чем
                полезна — по ней не поймёшь, вернёшь ты удалённый урок или
                чужую правку получасовой давности. Что именно она тронет,
                стоит в подсказке.

                Стоит она **последней в ряду и прижата к правому краю**
                (`margin-left: auto`), а не между добавлением и меню.
                Отмена — не соседка тому, что делают каждый день: она
                появляется и исчезает, и, стоя в середине, каждым своим
                появлением сдвигала бы меню под курсором. У правого края
                двигать нечего, а место у неё то же, где действия-исходы
                стоят и в окнах.

                Перенос сделан в разметке, а не `order`: порядок обхода с
                клавиатуры обязан совпадать с видимым.
              */}
              {(moves.undo || moves.redo) && (
                <span className="plan-walk">
                  {moves.undo && (
                    <button
                      type="button"
                      className="secondary plan-undo"
                      disabled={busy}
                      title={
                        moves.undo.detail
                          ? t('plan.undo.what', {
                              action: nameOf(moves.undo),
                              detail: moves.undo.detail,
                              who: moves.undo.mine
                                ? t('plan.undo.mine')
                                : (moves.undo.who?.name ?? ''),
                            })
                          : undefined
                      }
                      onClick={() => undo()}
                    >
                      {t('plan.undo.label', { action: nameOf(moves.undo) })}
                    </button>
                  )}

                  {/*
                    «Вернуть» появляется, только когда есть куда: ход назад
                    начат и впереди осталось состояние. Постоянная кнопка,
                    умеющая только отказать, честнее не нарисованная — то же
                    правило, по которому у проведённой строки нет ручки.
                  */}
                  {moves.redo && (
                    <button
                      type="button"
                      className="secondary plan-redo"
                      disabled={busy}
                      title={
                        moves.redo.detail
                          ? t('plan.redo.what', {
                              action: nameOf(moves.redo),
                              detail: moves.redo.detail,
                            })
                          : undefined
                      }
                      onClick={() => redo()}
                    >
                      {t('plan.redo.label', { action: nameOf(moves.redo) })}
                    </button>
                  )}
                </span>
              )}
            </div>

            {helpOpen && <PlanCsvHelp />}

            {/*
              Метка о чужой правке — маленькая, но своя строка.

              Администратор вправе чинить содержание курсов школы, и учитель
              узнаёт об этом, только открыв план: изменившиеся строки без
              объяснения читаются как поломка. Поэтому здесь сказано, кто и
              когда, и рядом стоит возврат — не «пожаловаться», а «вернуть
              как было».
            */}
            {intervention && (
              <p className="hint plan-intervention">
                {t('plan.intervention.mark', {
                  who: intervention.who?.name ?? '',
                  // `shortDate` читает дату, а не момент: соседний
                  // вызов у эталона режет так же
                  when: shortDate(intervention.made_at.slice(0, 10)),
                })}{' '}
                <button
                  type="button"
                  className="link"
                  disabled={busy}
                  onClick={() => undo(intervention.id)}
                >
                  {t('plan.intervention.revert')}
                </button>
              </p>
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
                  removeSection: askRemoveSection,
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
              {chosen.length > 0 && (
                <div className="selection-bar plan-selection">
                  <span>
                    {t('plan.picked', {
                      lessons: t('common.lessonCount', { count: chosen.length }),
                    })}
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
              // на полке это имя шаблона: вопрос «чей это план» тот же, и
              // ответ на него у полки есть — просто не курсом
              course: onShelf ? (shelfCard?.title ?? null) : (course?.name ?? null),
              taught: Boolean(nodeById.get(opened)?.taught),
              date: layout.byId.get(opened)?.slot?.date ?? null,
            }}
            onClose={() => {
              setOpened(null)
              if (returnTo) navigate(returnTo)
            }}
            // the marks in the table come from the tree, so a save has to be
            // followed by a re-read — the paperclip appears the moment a file does
            onSaved={() => load(owner).catch(handleError)}
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
          onEdit={(item) => navigate(`/library/${item.id}`)}
          onCreate={() => setDialog({ type: 'newTemplate' })}
          onPublish={publishTemplate}
          onKeepUpdating={keepUpdating}
          onDelete={removeTemplate}
          onClose={() => setDialog(null)}
        />
      )}

      {preview && (
        <TemplateView
          template={preview}
          busy={busy}
          // без выбора — весь план и заменой, как было; с выбором —
          // дописыванием: конструктор складывает, а не начинает заново
          onUse={(picked) =>
            takeTemplate({ template: preview.id, mode: 'replace', ...(picked ?? {}) })
          }
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

      {/*
        Новый план на полке — та же форма, что у «положить на полку», только
        без курса. Второй формы тут заводить незачем: вопросы одни и те же —
        название, предмет, параллель, кому видно, — а `PublishDialog` без
        курса как раз и спрашивает предмет с параллелью сам.

        Кому видно, решает человек, а не мы за него. Соблазн положить пустой
        план черновиком принудительно был, и он неверен: тумблер в форме
        спрашивает прямо, и молча ответить за него значит показать одно, а
        сделать другое.
      */}
      {dialog?.type === 'newTemplate' && (
        <PublishDialog
          course={null}
          subjects={subjects}
          existing={null}
          fresh
          busy={busy}
          onSubmit={(fields) => {
            setBusy(true)
            createTemplate(fields)
              .then((made) => {
                setDialog(null)
                navigate(`/library/${made.id}`)
              })
              .catch(handleError)
              .finally(() => setBusy(false))
          }}
          onClose={() => setDialog(null)}
        />
      )}

      {overwrite && (
        <OverwriteDialog
          what={overwrite.what}
          diff={overwrite.diff}
          busy={busy}
          onConfirm={overwrite.apply}
          onClose={() => setOverwrite(null)}
        />
      )}

      {dialog?.type === 'publish' && (
        <PublishDialog
          course={course}
          subjects={subjects}
          // копия просит ту же форму, что и первое сохранение: у неё своё
          // название, иначе на полке лягут два «Алгебра 9» без различий
          existing={dialog.copy ? null : mineOnShelf}
          copy={Boolean(dialog.copy)}
          busy={busy}
          onSubmit={(fields) => {
            const refreshing = Boolean(mineOnShelf && !dialog.copy)

            /*
             * Обновление спрашивает, а первое сохранение — нет.
             *
             * Раньше «Обновить» переписывало строки молча, и это было
             * безопасно ровно потому, что шаблон был снимком плана: своей
             * работы в нём не было. Теперь она там есть — план на полке
             * пишут руками, — и молчаливая перезапись стирала бы написанное.
             *
             * Класть **новый** шаблон при этом не о чем спрашивать: он
             * пустой, терять нечего.
             */
            if (refreshing) {
              setBusy(true)
              fetchRefreshDiff(mineOnShelf.id, classId)
                .then((diff) =>
                  setOverwrite({
                    what: t('plan.overwrite.refresh', {
                      title: mineOnShelf.title,
                    }),
                    diff,
                    apply: () => {
                      setBusy(true)
                      return refreshTemplate(mineOnShelf.id, classId)
                        .then((template) => {
                          setTemplates((current) => [
                            ...current.filter((item) => item.id !== template.id),
                            template,
                          ])
                          setNotice(
                            t('plan.published', { title: template.title }),
                          )
                          setOverwrite(null)
                          setDialog(null)
                        })
                        .catch(handleError)
                        .finally(() => setBusy(false))
                    },
                  }),
                )
                .catch(handleError)
                .finally(() => setBusy(false))
              return
            }

            const request = publishPlan({
              course: classId,
              ...fields,
              // копия не претендует на ведение: её никто не перезапишет
              is_live: !dialog.copy,
            })

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

          {/*
            Цена — в самой кнопке, а не рядом с ней.

            Две кнопки стояли рядом, обе разрушительные, и разница между
            ними была в одном слове: «оставить» против «вместе». Промах
            стоил шести уроков с содержанием. Теперь вторая называет, что
            именно унесёт, а при потере содержания ещё и требует галочку —
            тот же приём, что у импорта, и по той же причине: там, где
            теряется только название, лишних вопросов не задают.
          */}
          {sectionPrice.lost && (
            <label className="checkbox danger">
              <input
                type="checkbox"
                checked={dropSection}
                onChange={(event) => setDropSection(event.target.checked)}
              />
              {t('plan.removeSection.confirmLoss', {
                content: sectionPrice.content,
                attachments: sectionPrice.attachments,
              })}
            </label>
          )}

          <div className="actions">
            <button type="button" disabled={busy} onClick={() => removeSection(true)}>
              {t('plan.removeSection.keep')}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={
                busy ||
                deleting.children.some((child) => child.taught) ||
                (sectionPrice.lost && !dropSection)
              }
              onClick={() => removeSection(false)}
            >
              {/* счётчик настоящий, а не склеенный из готовой формы:
                  «вместе с 5 уроков» — не по-русски, а подставить сюда
                  `lessonCount` значит собрать фразу руками */}
              {deleting.children.length
                ? t('plan.removeSection.withCount', {
                    count: deleting.children.length,
                  })
                : t('plan.removeSection.withChildren')}
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
          // одну строку окно называет по имени, пачку — числом: «удалить
          // 1 урок?» не говорит, какой именно, а крестик нажимают у
          // конкретной строки
          title={
            dropping.length === 1
              ? t('plan.dropPicked.one', { title: titleOf(dropping[0]) })
              : t('plan.dropPicked.title', {
                  lessons: t('common.lessonCount', { count: dropping.length }),
                })
          }
        >
          {priceOf(dropping).lost && (
            <p className="hint">
              {t('plan.dropPicked.cost', {
                content: priceOf(dropping).content,
                attachments: priceOf(dropping).attachments,
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
function PublishDialog({
  course,
  subjects,
  existing,
  copy = false,
  // новый план на полке: та же форма, но она не «сохраняет» готовое, а
  // заводит пустое — и называться должна тем же словом, каким её позвали
  fresh = false,
  busy,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  const [title, setTitle] = useState(() => {
    const name = course
      ? `${course.subject_name ?? ''} ${course.grade_name ?? ''}`.trim()
      : ''
    // У копии название по умолчанию с датой: два «Алгебра 9» на полке
    // различить нельзя, а копию кладут именно затем, чтобы к ней вернуться.
    // Дата — через `dates.js`, то есть по языку интерфейса: своего формата
    // тут заводить нельзя, он разъедется с остальными датами в проекте
    return copy && name ? `${name} — ${longDate(today())}` : name
  })
  const [description, setDescription] = useState('')
  const [subject, setSubject] = useState(subjects[0]?.id ?? null)
  const [grade, setGrade] = useState('')
  /*
   * Кому видно — вопрос того же разговора, что название и описание.
   *
   * Раньше шаблон всегда ложился черновиком, а «Опубликовать» жило
   * отдельной кнопкой в окне полки: положить на полку и положить на
   * **общую** полку были двумя действиями в разных местах, и второе
   * забывалось — на полке лежал черновик, которого никто, кроме автора, не
   * видел. Умолчание при этом «всей школе»: кладут туда ради того, чтобы
   * этим пользовались.
   */
  const [published, setPublished] = useState(true)

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
              is_published: published,
              ...(asksSubject ? { subject } : {}),
              ...(asksGrade ? { grade } : {}),
            })
          }
        }}
      >
        <h3>
          {t(
            fresh
              ? 'plan.shelf.create'
              : copy
                ? 'plan.publishCopy'
                : 'plan.publish',
          )}
        </h3>
        {/* копия обещает ровно одно — что останется такой; сказать это надо
            здесь, иначе разница с соседним пунктом меню только в слове */}
        {copy && <p className="hint">{t('plan.publishCopyHint')}</p>}

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

        <div className="field">
          {/* подпись видимая, как у соседних полей: тумблер без неё
              выглядел приблудой между «Заметкой» и кнопками */}
          <label>{t('plan.visibility')}</label>
          <Switch
            label={t('plan.visibility')}
            value={published}
            onChange={setPublished}
            options={[
              { value: true, label: t('plan.toEveryone') },
              { value: false, label: t('plan.toMyself') },
            ]}
          />
          <p className="hint">
            {published ? t('plan.toEveryoneHint') : t('plan.toMyselfHint')}
          </p>
        </div>

        <div className="actions">
          <button type="submit" disabled={busy || !title.trim()}>
            {t(
              fresh
                ? 'plan.shelf.create'
                : copy
                  ? 'plan.publishCopy'
                  : 'plan.publish',
            )}
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
 * Переписать план — но сперва показать, что именно уйдёт.
 *
 * Действий, стирающих план целиком, в проекте два: взять шаблон «целиком» в
 * курс и обновить шаблон с курса. Оба долго молчали, и оба были при этом
 * безопасны: план на полке был снимком, своей работы в нём не было. Теперь
 * есть — его пишут руками, — и молчаливая перезапись стирала бы написанное.
 *
 * Строки показывает **тот же** `DiffBody`, что и сравнение с эталоном:
 * вопрос один — «что именно изменится», — и второй его разметки быть не
 * должно. Разные списки для одного ответа расходятся в первой же правке.
 *
 * Когда родства между планами нет — шаблон писали руками, план набирали с
 * нуля, — сравнение молчит и говорит числами. Показать вместо этого список,
 * где каждая строка удалена и каждая добавлена, было бы формально правдой,
 * а читалось бы как поломка.
 *
 * Отмену это не отменяет и не заменяет: снимок берётся перед записью, и
 * ошибку возвращает одна кнопка. Вопрос тут — чтобы не ошибиться, отмена —
 * чтобы ошибка не стоила дня.
 */
function OverwriteDialog({ what, diff, busy, onConfirm, onClose }) {
  const { t } = useTranslation()

  return (
    <Modal onClose={onClose} title={what}>
      {diff.matched ? (
        <DiffBody data={diff} caption={t('plan.overwrite.caption')} />
      ) : (
        <p className="hint">
          {t('plan.overwrite.unrelated', {
            replacing: diff.replacing,
            arriving: diff.arriving,
          })}
        </p>
      )}

      <div className="actions">
        <button type="button" disabled={busy} onClick={onConfirm}>
          {t('plan.overwrite.confirm')}
        </button>
        <button type="button" className="secondary" onClick={onClose}>
          {t('common.cancel')}
        </button>
      </div>
    </Modal>
  )
}
