import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
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
import { EmptyDropZone, SortableRow, dragId, emptyZoneId } from './PlanDnd'
import { Link } from 'react-router-dom'
import { dayMonth, shortDate, shortWeekday, weekdayWithDate } from './dates'
import { resolveDropTarget } from './planLogic'
import { today } from './calendarLogic'
import { useDismissable } from './UserMenu'
import MathText from './MathText'
import Switch from './Switch'
import { remember, remembered } from './remember'

/**
 * Таблица учебного плана: строки, недели, черты и свободные слоты.
 *
 * Отделена от `Plan.jsx` не ради размера файла, а потому что у страницы и у
 * таблицы разные поводы меняться. Страница — это диалоги, импорт, полка и
 * эталон; таблица — вёрстка, которую переделывали трижды и у которой есть
 * свои сторожа (`e2e/tests/planDates.spec.js`). Пока они жили в одной
 * функции на тридцать три `useState`, правка колонки шла рядом с логикой
 * публикации шаблона, и соседнее ломалось раз за разом.
 *
 * **Запросов отсюда не уходит ни одного.** Всё, что меняет данные, уезжает
 * наверх колбэками: страница знает про `busy`, ошибки и перечитывание
 * дерева, таблица — только про то, как это показать. Перетаскивание
 * поделено по той же линии: сенсоры, попадание курсора и подсветка цели
 * здесь, а запрос на перенос — `actions.moveTo` наверх.
 *
 * Колбэки собраны в один `actions`, а не разложены по пропсам поодиночке:
 * их одиннадцать, и списком они читаются как то, что таблица умеет
 * попросить у страницы, а не как одиннадцать разных настроек. Данные и вид
 * остались плоскими — их смотрят по одному.
 *
 * **`React.memo` здесь нет, и это решение, а не забывчивость.** Семь
 * колбэков из двадцати пропсов пересоздаются на каждом рендере страницы, и
 * чтобы memo хоть раз сработала, их пришлось бы обернуть в `useCallback`
 * вместе с общим для них `run` — восемь списков зависимостей, каждый из
 * которых при ошибке даёт замыкание на старые данные. Мерили, что это
 * купит: лишняя перерисовка страницы с планом на сорок уроков и полусотней
 * свободных слотов (623 узла) стоит 0.45 мс, из них доля таблицы — 0.28 мс
 * (та же страница с пустым планом обходится в 0.17 мс). Случается она на
 * редких действиях: открыли диалог, показали сообщение, развернули справку.
 *
 * А настоящий частый перерендер — перетаскивание, где `setDrop` срабатывает
 * на каждое движение курсора, — идёт от **своего** состояния, и memo на
 * него не влияет никак.
 *
 * Что осталось наверху и приезжает пропсами: `editing`, `adding` и
 * `collapsed`. Первые два — потому что формы рисуются в строках, а
 * открывают их и кнопки под таблицей («Добавить урок», «Добавить тему»), и
 * `openAdd` заодно снимает переименование. Свёрнутые темы — потому что
 * таблица размонтируется на время загрузки другого курса, а свёрнутое при
 * возврате должно остаться свёрнутым: срок жизни у этого состояния
 * страничный, а не табличный.
 */

const FREE_OPEN_KEY = 'planFreeOpen'

// столько свободных слотов показываем сразу: свернуть три строки — значит
// заставить нажать кнопку ради трёх строк
const FREE_INLINE = 5

const EMPTY_SET = new Set()

export default function PlanTable({
  nodes,
  layout,
  blocks,
  dated,
  busy,
  collapsed,
  editing,
  adding,
  spotlight = null,
  spotlightSlot = null,
  debts = EMPTY_SET,
  // выбор строк пачкой: сама таблица его только показывает и сообщает о
  // нажатиях, а что выбрано и что с этим делать — знает страница
  selecting = false,
  selected = EMPTY_SET,
  actions,
}) {
  const {
    toggleSection,
    changeEditing,
    submitEdit,
    changeAdding,
    add,
    submitAdd,
    openLesson,
    removeLesson,
    removeSection,
    move,
    moveTo,
    pick,
  } = actions
  const { t } = useTranslation()
  // the screen-reader script for dragging: dnd-kit reads it out on pick-up
  const dndInstructions = { draggable: t('plan.dndInstructions') }

  const [freeOpen, setFreeOpen] = useState(() => remembered(FREE_OPEN_KEY, false))
  const [dragged, setDragged] = useState(null) // {node} — what is being dragged
  /*
   * Строка «в руке»: стрелки отрываются от списка.
   *
   * Поднять урок на три позиции — три нажатия по одной кнопке, а после
   * первого строки меняются местами, и второе приходится уже по соседу.
   * Курсор двигать браузер не даёт; прокрутка страницы под курсор помогает
   * не всегда — выше нуля не прокрутишь, и на коротком плане тоже нечем.
   *
   * Поэтому после первого нажатия на том же месте появляется маленький
   * плавающий блок со стрелками: он не двигается вообще никогда, ходит
   * строка, и она же подсвечена. Никакой магии — видно, что взяли, и
   * видно что именно.
   */
  const [held, setHeld] = useState(null) // {id, isSection, up, down}
  const [drop, setDrop] = useState(null) // {overId, side, parent, index}
  const titleRef = useRef(null) // поле названия открытой формы добавления
  const formRef = useRef(null) // сама форма: по ней решается «клик мимо»

  /**
   * Escape закрывает форму добавления — откуда угодно.
   *
   * Слушатель на документе, а не на форме, и это не перестраховка: форма
   * теперь остаётся открытой после добавления, то есть живёт долго, а
   * фокус за это время уходит куда угодно — на кнопку, которая погасла, в
   * тумблер, просто мимо. «Нажал не туда, и Escape перестал работать»
   * читается как поломка, а не как правило.
   */
  const open = Boolean(adding)
  useEffect(() => {
    if (!open) return undefined

    const escape = (event) => {
      if (event.key === 'Escape') changeAdding(null)
    }

    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [open, changeAdding])

  /**
   * Клик мимо закрывает **пустую** форму.
   *
   * Форма остаётся открытой после добавления — это то, ради чего её и
   * оставили: уроки заводят подряд. Но человек уходит к другому делу, и
   * пустая форма продолжает висеть посреди плана, ожидая нажатия, о котором
   * он уже не помнит. Ждать ей при этом нечего: в ней ничего не набрано.
   *
   * Набранное закрытием не выбрасывается никогда: текст в поле — это
   * незаконченная работа, и уносить её кликом мимо нельзя. Такая форма
   * держится до Escape или «Закрыть».
   *
   * Слушаем `pointerdown`, а не `click`: он приходит раньше, поэтому «+» у
   * другой строки успевает открыть свою форму после того, как закрылась эта.
   */
  const draft = adding?.title?.trim() ?? ''
  useEffect(() => {
    if (!open || draft) return undefined

    const away = (event) => {
      if (!formRef.current?.contains(event.target)) changeAdding(null)
    }

    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open, draft, changeAdding])

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

  const items = useMemo(() => {
    const map = new Map()

    ;(nodes ?? []).forEach((node, index) => {
      const children = node.children ?? []
      const numbers = children.map((child) => child.number).filter(Boolean)

      const entry = {
        id: dragId(node.id),
        node,
        parent: null,
        index,
        // сквозные номера нужны, чтобы понять, куда строка приземлится
        // относительно проведённых: у темы это номера её уроков
        number: node.number ?? null,
        first: numbers.length ? Math.min(...numbers) : null,
        last: numbers.length ? Math.max(...numbers) : null,
        count: children.length,
      }
      map.set(entry.id, entry)

      children.forEach((child, childIndex) => {
        map.set(dragId(child.id), {
          id: dragId(child.id),
          node: child,
          parent: node.id,
          index: childIndex,
          number: child.number ?? null,
          // ссылка на блок: наведение на урок внутри темы — это цель для
          // самой темы, а её шапкой в такой момент никто не целится
          section: entry,
        })
      })
    })

    return map
  }, [nodes])

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
      boundary,
    })

    // куда рисовать черту, решает сам расчёт: у темы целью становится весь
    // блок, а не та строка, над которой стоит курсор
    return target
  }

  const handleDragStart = (event) => {
    changeEditing(null)
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

    if (target && node) moveTo(node.id, target.parent, target.index)
  }

  // --- editing ---

  /**
   * Renaming, for folders.
   *
   * A lesson is not renamed here: clicking it opens the panel, where the
   * title sits above its content. A folder has no content, so a folder is
   * just a name and an inline field is the shortest way to change it.
   */
  const startEdit = (node) => changeEditing({ id: node.id, title: node.title })

  const editKeyDown = (event) => {
    if (event.key === 'Escape') changeEditing(null)
  }

  // --- rendering ---

  const editForm = () => (
    <form className="plan-edit" onSubmit={submitEdit}>
      <input
        autoFocus
        value={editing.title}
        maxLength={200}
        aria-label={t('plan.titleLabel')}
        onChange={(event) => changeEditing({ ...editing, title: event.target.value })}
        onKeyDown={editKeyDown}
      />
      <button type="submit" disabled={busy}>
        {t('common.save')}
      </button>
      <button type="button" className="secondary" onClick={() => changeEditing(null)}>
        {t('common.cancel')}
      </button>
    </form>
  )

  /**
   * Сколько уроков уедет в новую тему — счёт до нажатия, а не после.
   *
   * Разрез отвечает на «начинается новый раздел»: хвост темы переезжает
   * под новый заголовок. Число тут единственное, чего не видно глазами:
   * хвост бывает в десяток строк и уходит за край экрана.
   */
  const tailAfter = (parent, after) => {
    if (!parent || !after) return 0

    const section = (nodes ?? []).find((node) => node.id === parent)
    const children = section?.children ?? []
    const index = children.findIndex((child) => child.id === after)

    return index < 0 ? 0 : children.length - index - 1
  }

  /**
   * Добавили — и курсор возвращается в поле.
   *
   * Форма остаётся открытой ради ввода подряд, но кнопка «Добавить» с
   * пустым полем гаснет, а погасшая кнопка теряет фокус: нажали мышью — и
   * фокус уехал в `body`. Печатать следующий урок было некуда, а Escape
   * улетал мимо формы.
   */
  const finishAdd = async (event, options) => {
    await submitAdd(event, options)
    titleRef.current?.focus()
  }

  const addForm = () => (
    <form className="plan-add-form" onSubmit={finishAdd} ref={formRef}>
      {/* Что заводим — урок или тему. Спрашивается только у «вставить
          после»: две кнопки над таблицей и «+» в шапке темы отвечают на
          этот вопрос сами, а тема внутри темы не кладётся вовсе. */}
      {!adding.fixedKind && (
        <Switch
          label={t('plan.addKind')}
          value={adding.is_section}
          disabled={busy}
          onChange={(value) => changeAdding({ ...adding, is_section: value })}
          options={[
            { value: false, label: t('plan.kindLesson') },
            { value: true, label: t('plan.kindSection') },
          ]}
        />
      )}
      <input
        autoFocus
        ref={titleRef}
        value={adding.title}
        maxLength={200}
        placeholder={t(
          adding.is_section ? 'plan.sectionPlaceholder' : 'plan.lessonPlaceholder',
        )}
        aria-label={t('plan.titleLabel')}
        onChange={(event) => changeAdding({ ...adding, title: event.target.value })}
      />
      <button type="submit" disabled={busy || !adding.title.trim()}>
        {t('common.add')}
      </button>
      {/* Вторая кнопка называет то, что сделает: пустое поле — «Закрыть»,
          набранное — «Готово», то есть добавить и на этом закончить. Пока
          она всегда была «Готово», кнопка с этим именем выбрасывала
          набранное название — самое дорогое, что она могла сделать. */}
      <button
        type="button"
        className="secondary"
        disabled={busy}
        onClick={(event) =>
          adding.title.trim() ? finishAdd(event, { close: true }) : changeAdding(null)
        }
      >
        {t(adding.title.trim() ? 'plan.done' : 'common.close')}
      </button>
      {adding.is_section && tailAfter(adding.parent, adding.after) > 0 && (
        <span className="hint">
          {t('plan.splitTail', { count: tailAfter(adding.parent, adding.after) })}
        </span>
      )}
    </form>
  )

  /**
   * Форма стоит там, где появится строка.
   *
   * Ключ — пара «родитель и якорь»: `before` в него не входит намеренно. Он
   * живёт ровно до первой вставки (нужен, чтобы строка встала первой в
   * теме), а место формы обязано пережить её: после вставки форма
   * переезжает за созданную строку, и якорем становится она.
   */
  const addFormFor = (parent, after) =>
    adding && adding.parent === parent && adding.after === after ? addForm() : null

  /**
   * Проведённая строка стоит на месте — и тема, в которой такая есть.
   *
   * Раскладка двухступенчатая: час со связью показывает свой урок, а
   * соседи разбирают оставшиеся по порядку. Переставленная связанная
   * строка вытеснила бы их неизвестно куда, и сервер такой перенос
   * отклоняет; кнопки убраны затем, чтобы это было видно до нажатия.
   */
  const locked = (node) =>
    Boolean(node.taught) || (node.children ?? []).some((child) => child.taught)

  /**
   * Сквозной номер последней проведённой строки — граница прошлого.
   *
   * Запрет двусторонний: проведённую строку не двигают (`locked`), а
   * непроведённую не ставят перед ней. Без второй половины первая
   * обходилась с другого конца — мартовскую строку никто не трогал, а
   * сентябрьскую перетаскивали ей за спину.
   */
  const boundary = useMemo(() => {
    let last = 0

    const visit = (node) => {
      if (node.taught && node.number) last = Math.max(last, node.number)
    }

    ;(nodes ?? []).forEach((node) => {
      visit(node)
      ;(node.children ?? []).forEach(visit)
    })

    return last
  }, [nodes])

  /**
   * Можно ли вставить строку **после** этой.
   *
   * Правило одно на все случаи: новая строка встанет следом, то есть на
   * номер +1, и он должен быть строго за границей. У проведённой это
   * значит «только у последней» — за ней место свободно; у непроведённой,
   * оказавшейся перед границей, «+» не показываем вовсе: сервер откажет
   * (`plan_before_taught`), а кнопка, умеющая только отказать, обещает
   * то, чего не будет.
   *
   * Тема спрашивает то же про свой последний урок: «+» в её шапке
   * дописывает в конец блока. Пустая тема номеров не имеет — там и мерить
   * нечего, спросит сервер.
   */
  const mayInsertAfter = (node) => {
    if (!boundary) return true

    if (node.is_section) {
      const numbers = (node.children ?? []).map((child) => child.number).filter(Boolean)
      return numbers.length === 0 || Math.max(...numbers) >= boundary
    }

    return (node.number ?? 0) >= boundary
  }

  /**
   * Можно ли вставить строку **первой в тему**.
   *
   * Строка займёт место нынешнего первого урока, а всё, что ниже, съедет на
   * единицу. Значит непроведённая строка окажется перед проведёнными, если
   * граница проходит по этой теме или ниже её начала: сервер такое
   * отклоняет (`plan_before_taught`), а кнопка, умеющая только отказать,
   * обещает то, чего не будет.
   *
   * У пустой темы номеров нет, мерить нечего — там спросит сервер, как и
   * спрашивал.
   */
  const mayInsertFirst = (section) => {
    if (!boundary) return true

    const numbers = (section.children ?? []).map((child) => child.number).filter(Boolean)
    return numbers.length === 0 || Math.min(...numbers) > boundary
  }

  /** Выше подниматься некуда: там уже проведённые уроки. */
  const beforeTaught = (node) => {
    if (!boundary) return false

    const numbers = node.is_section
      ? (node.children ?? []).map((child) => child.number).filter(Boolean)
      : [node.number].filter(Boolean)

    return numbers.length > 0 && Math.min(...numbers) <= boundary + 1
  }

  /**
   * Кнопки перестановки: у проведённой строки их нет, у следующей за ней
   * не нажимается верхняя.
   *
   * Разница не в строгости, а в том, о чём вопрос. Проведённая строка не
   * двигается никуда и никогда — предлагать ей движение незачем, как незачем
   * ей и ручка. А непроведённая двигается свободно, просто не выше границы,
   * и вот тут кнопка нужна на месте: пропавшая читалась бы как «сюда вообще
   * нельзя», а нельзя ей ровно в одну сторону.
   */
  const closeHeld = useCallback(() => setHeld(null), [])
  const heldRef = useDismissable(Boolean(held), closeHeld)

  /**
   * Взять строку в руку.
   *
   * Геометрию берём у самих кнопок ряда, обеих: плавающий блок повторяет
   * их положение пиксель в пиксель, и нажатая стрелка оказывается ровно
   * под курсором — считать отступы руками не надо.
   */
  const pickUp = (button, node, isSection) => {
    const arrows = [...button.parentElement.querySelectorAll('button')].slice(0, 2)
    if (arrows.length < 2) return

    const [up, down] = arrows.map((arrow) => arrow.getBoundingClientRect())
    setHeld({ id: node.id, isSection, up, down })
  }

  /** Узел, который держат: его могло не стать — курс сменили, строку снесли. */
  const heldNode = useMemo(() => {
    if (!held) return null

    for (const node of nodes ?? []) {
      if (node.id === held.id) return node
      for (const child of node.children ?? []) if (child.id === held.id) return child
    }

    return null
  }, [held, nodes])

  const heldNoRoom = heldNode ? locked(heldNode) || beforeTaught(heldNode) : false

  const moveButtons = (node, isSection) => {
    if (locked(node)) return null

    const noRoom = beforeTaught(node)

    return (
      <>
        <button
          type="button"
          className="link"
          title={t(noRoom ? 'plan.beforeTaught' : 'plan.up')}
          disabled={busy || noRoom}
          onClick={(event) => {
            pickUp(event.currentTarget, node, isSection)
            move(node.id, 'up', isSection)
          }}
        >
          ↑
        </button>
        <button
          type="button"
          className="link"
          title={t('plan.down')}
          disabled={busy}
          onClick={(event) => {
            pickUp(event.currentTarget, node, isSection)
            move(node.id, 'down', isSection)
          }}
        >
          ↓
        </button>
      </>
    )
  }

  const indicatorFor = (id) => (drop?.overId === dragId(id) ? drop.side : null)

  /**
   * Строка, на которую привели по ссылке со страницы урока.
   *
   * Подсветка одноразовая и гаснет сама (анимация в стилях): страница
   * перечитывает дерево после каждой правки, и подсветка, живущая до
   * ухода со страницы, к третьей правке читалась бы как выделение.
   */
  const spotlightFor = (id) => (id === spotlight ? ' spotlight' : '')

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
          {/* дата рядом со словом: черта стоит перед первым непрошедшим
              уроком, и «сегодня» без числа не говорит, где именно сегодня
              на этой ленте. Тире, а не двоеточие: это не подпись со
              значением, а одна фраза — и набрана она поэтому одинаково,
              от слова до числа */}
          <span className="plan-today-label">{t('plan.today')} –</span>
          {/* дата приезжает в самой метке: по ней же лента и решает, выше
              или ниже соседних черт эта стоит */}
          <span className="plan-today-date">
            {weekdayWithDate(mark.date ?? today())}
          </span>
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
        {week?.labelled && t('plan.week', { number: week.number })}
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
    if (!dated || !free.length) return null

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
          <ul className={selecting ? 'plan free selecting' : 'plan free'}>
            {free.map(({ slot, labelled }) => (
              <li
                key={slot.id}
                // якорь для ссылки со страницы занятия: «допишите строку»
                // должно приводить к нужному дню, а не «в план вообще»
                data-slot={slot.id}
                className={
                  `plan-row free${slot.week % 2 === 0 ? ' week-even' : ''}` +
                  (slot.id === spotlightSlot ? ' spotlight' : '')
                }
              >
                {selectCell()}
                <span className="plan-weekmark">
                  {labelled && t('plan.week', { number: slot.week })}
                </span>
                <span className="plan-state" />
                <Link
                  className="plan-date"
                  to={`/lesson/${slot.id}`}
                  title={t('plan.openLesson')}
                >
                  {dayMonth(slot.date)} <em>{shortWeekday(slot.date)}</em>
                </Link>
                {/* ни ручки, ни номера: это не строка плана, а пустое место
                    в расписании */}
                <span />
                <span />
                <span className="plan-title-cell">
                  <button
                    type="button"
                    className="link title free-slot"
                    disabled={busy}
                    onClick={() => add({ parent: null, fixedKind: true })}
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

  /**
   * Флажок выбора — первой колонкой, и только в режиме выбора.
   *
   * Ячейка эта есть у **каждой** строки, включая тему и свободный слот:
   * сетка одна на все строки, и колонка, появившаяся не везде, сдвинула бы
   * соседние относительно друг друга. У темы и свободного слота она пустая
   * — выбирают уроки (см. `selectableIds`).
   *
   * Shift тянет диапазон от прошлого нажатия: десять строк подряд иначе
   * это десять нажатий, а именно от них и уходим.
   */
  const selectCell = (node = null) => {
    if (!selecting) return null
    if (!node || node.is_section || node.taught) return <span className="plan-pick" />

    return (
      <span className="plan-pick">
        <input
          type="checkbox"
          checked={selected.has(node.id)}
          disabled={busy}
          aria-label={node.title}
          onClick={(event) => pick(node.id, { range: event.shiftKey })}
          // выбор ведёт onClick: только он знает про Shift
          onChange={() => {}}
        />
      </span>
    )
  }

  /** Чётные недели закрашены — этим и группируются. */
  const weekStripe = (node) => {
    const week = dated && layout.byId.get(node.id)?.week
    return week && week.number % 2 === 0 ? ' week-even' : ''
  }

  /**
   * Дата и день недели урока — узкая колонка слева.
   *
   * У темы даты нет (её диапазон стоит в полосе), но ячейка нужна пустой:
   * иначе полоса съехала бы влево относительно строк уроков.
   *
   * **Дата — ссылка на занятие.** Строка плана отвечает «что проходим», а
   * занятие — «как оно прошло»: журнал, работы, отмена. Раньше из плана в
   * занятие пути не было вовсе, хотя обратный (со страницы занятия в план)
   * мы завели давно. Ведёт именно дата: она и есть то место строки, где
   * речь заходит о конкретном дне.
   */
  const dateCells = (node, empty = false) => {
    if (!dated) return null
    if (empty) {
      return (
        <>
          <span className="plan-state" />
          <span className="plan-date" />
        </>
      )
    }
    const slot = layout.byId.get(node.id)?.slot

    // три состояния часа, и все три видно на своей строке: записан (за ним
    // стоит проведённое занятие), долг (прошёл, а записи нет) и обычный.
    // По ним и видно, где учёт остановился
    const unclosed = debts.has(slot?.id)
    const recorded = Boolean(slot?.lesson_id)
    const mark = recorded ? ' recorded' : unclosed ? ' unclosed' : ''

    return (
      <>
        <span
          className={`plan-state${mark}`}
          title={
            mark ? t(recorded ? 'plan.recordedHint' : 'plan.unclosedHint') : undefined
          }
        >
          {recorded ? '✓' : unclosed ? '•' : ''}
        </span>
        {slot ? (
          <Link
            className="plan-date"
            to={`/lesson/${slot.id}`}
            title={t('plan.openLesson')}
          >
            {dayMonth(slot.date)} <em>{shortWeekday(slot.date)}</em>
          </Link>
        ) : (
          <span className="plan-date missing">{t('plan.noSlot')}</span>
        )}
      </>
    )
  }

  const renderLesson = (node, parent) => (
    <SortableRow
      key={node.id}
      id={dragId(node.id)}
      className={
        'plan-row lesson' +
        weekStripe(node) +
        spotlightFor(node.id) +
        (held?.id === node.id ? ' held' : '') +
        (dated && !layout.byId.get(node.id)?.slot ? ' no-slot' : '') +
        (dated && layout.byId.get(node.id)?.past ? ' past' : '')
      }
      indicator={indicatorFor(node.id)}
      locked={locked(node)}
    >
      {(handle) => (
        <>
          {/* левая колонка: неделя и дата. Взгляд идёт по левому краю и
              должен встречать данные, а не служебную ручку */}
          {selectCell(node)}
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
              onClick={() => openLesson(node.id)}
            >
              {/* `$\sin(a+b)$` в сорока строках подряд читается хуже, чем
                  сама формула; в `title=` при этом остаётся исходный текст —
                  подсказка должна показывать то, что правят */}
              <MathText text={node.title} />
            </button>

            {/* Значков «есть содержание» и «есть вложения» тут больше нет.
                Они отвечали на вопрос, которого таблице не задают: за
                содержанием идут в строку, а не выбирают её по значку. Зато
                на сорока строках это восемьдесят картинок справа от
                названий — и они спорили с ✓ и • слева, которые как раз про
                состояние и нужны.

                Заметка урока ушла оттуда же и по той же причине: она
                отвечает на вопрос «что я себе про этот урок записал», а
                таблицу читают, чтобы увидеть **план** — сорок названий
                подряд. Половина строки под текст, который относится к
                одной из них, ломала этот взгляд; читают и правят заметку
                там же, где содержание, — в окне урока. */}
          </span>

          <span className="row-actions">
            {moveButtons(node, false)}
            {mayInsertAfter(node) && (
              <button
                type="button"
                className="link"
                title={t('plan.insertAfter')}
                disabled={busy}
                onClick={() => add({ parent, after: node.id })}
              >
                +
              </button>
            )}
            {!locked(node) && (
              <button
                type="button"
                className="link"
                title={t('common.delete')}
                disabled={busy}
                onClick={() => removeLesson(node)}
              >
                ✕
              </button>
            )}
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
        className={
          `plan-section${isTarget ? ' drop-inside' : ''}` +
          spotlightFor(node.id) +
          (held?.id === node.id ? ' held' : '')
        }
        indicator={indicatorFor(node.id)}
        locked={locked(node)}
      >
        {(handle) => (
          <>
            <div className={`plan-row section-head${weekStripe(node)}`}>
              {selectCell()}
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
                      <MathText text={node.title} />
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
                    {moveButtons(node, true)}
                    {/*
                      «+» везде значит одно: вставить **сразу под этой
                      строкой**. У шапки темы это её первый урок, а не
                      последний, — и до правки вставить урок в начало
                      непустой темы было нельзя вовсе, только перетаскиванием
                      через весь блок. Дописать в конец по-прежнему можно, и
                      тем же жестом: «+» у последнего урока темы.

                      Переключателя «Урок · Тема» здесь нет, и это не
                      недосмотр: тема в тему не кладётся. Разрезать блок
                      новой темой можно там, где разрез имеет смысл, — у
                      строки урока внутри него.
                    */}
                    {mayInsertFirst(node) && (
                      <button
                        type="button"
                        className="link"
                        title={t('plan.addToSection')}
                        disabled={busy}
                        onClick={() =>
                          add({
                            parent: node.id,
                            before: node.children?.[0]?.id ?? null,
                            // тема в тему не кладётся — спрашивать нечего
                            fixedKind: true,
                          })
                        }
                      >
                        +
                      </button>
                    )}
                    <button
                      type="button"
                      className="link"
                      title={t('plan.deleteSection')}
                      disabled={busy}
                      onClick={() => removeSection(node)}
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
                  {/* форма «первым уроком темы» стоит там, где строка и
                      появится, — над нынешним первым уроком */}
                  {addFormFor(node.id, null)}
                  {node.children.map((child, index) => (
                    <Fragment key={child.id}>
                      {/* у первого урока черта уже нарисована над полосой темы */}
                      {index > 0 && marks(child, 'before')}
                      {renderLesson(child, node.id)}
                      {addFormFor(node.id, child.id)}
                    </Fragment>
                  ))}
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

  return (
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
          items={nodes.map((node) => dragId(node.id))}
          strategy={verticalListSortingStrategy}
        >
          <ul
            className={
              (dated ? 'plan' : 'plan no-dates') + (selecting ? ' selecting' : '')
            }
          >
            {nodes.map((node) => (
              <Fragment key={node.id}>
                {/* черта, выпавшая на первый урок темы, встаёт над
                    её полосой: внутри блока она читалась бы как
                    часть темы, а это граница между ними */}
                {marks(node.is_section ? node.children?.[0] : node, 'before')}
                {node.is_section ? renderSection(node) : renderLesson(node, null)}
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

      {/* Стрелки, оторванные от списка: строка ходит, блок стоит. Ставим
          его ровно туда, где были кнопки строки, — нажатая стрелка
          остаётся под курсором, и второе нажатие попадает по ней же. */}
      {heldNode && (
        <div
          ref={heldRef}
          className="plan-held"
          style={{
            left: `${held.up.left - 4}px`,
            top: `${held.up.top - 2}px`,
            gap: `${Math.max(held.down.left - held.up.right, 0)}px`,
          }}
        >
          <button
            type="button"
            className="link"
            title={t(heldNoRoom ? 'plan.beforeTaught' : 'plan.up')}
            disabled={busy || heldNoRoom}
            style={{ width: `${held.up.width}px` }}
            onClick={() => move(held.id, 'up', held.isSection)}
          >
            ↑
          </button>
          <button
            type="button"
            className="link"
            title={t('plan.down')}
            disabled={busy}
            style={{ width: `${held.down.width}px` }}
            onClick={() => move(held.id, 'down', held.isSection)}
          >
            ↓
          </button>
        </div>
      )}
    </>
  )
}
