import { Fragment, useCallback, useMemo, useState } from 'react'
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
import { dayMonth, shortDate, shortWeekday } from './dates'
import { resolveDropTarget } from './planLogic'
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
  showWeeks,
  showFree,
  busy,
  collapsed,
  editing,
  adding,
  spotlight = null,
  debts = EMPTY_SET,
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
  } = actions
  const { t } = useTranslation()
  // the screen-reader script for dragging: dnd-kit reads it out on pick-up
  const dndInstructions = { draggable: t('plan.dndInstructions') }

  const [freeOpen, setFreeOpen] = useState(() => remembered(FREE_OPEN_KEY, false))
  const [dragged, setDragged] = useState(null) // {node} — what is being dragged
  const [drop, setDrop] = useState(null) // {overId, side, parent, index}

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
      map.set(dragId(node.id), { node, parent: null, index })
      ;(node.children ?? []).forEach((child, childIndex) => {
        map.set(dragId(child.id), { node: child, parent: node.id, index: childIndex })
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
    })

    return target && { ...target, overId, side: isBelow(event) ? 'after' : 'before' }
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
        onChange={(event) => changeAdding({ ...adding, title: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === 'Escape') changeAdding(null)
        }}
      />
      <button type="submit" disabled={busy || !adding.title.trim()}>
        {t('common.add')}
      </button>
      <button type="button" className="secondary" onClick={() => changeAdding(null)}>
        {t('plan.done')}
      </button>
    </form>
  )

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

  const moveButtons = (node, isSection) =>
    locked(node) ? null : (
      <>
        <button
          type="button"
          className="link"
          title={t('plan.up')}
          disabled={busy}
          onClick={() => move(node.id, 'up', isSection)}
        >
          ↑
        </button>
        <button
          type="button"
          className="link"
          title={t('plan.down')}
          disabled={busy}
          onClick={() => move(node.id, 'down', isSection)}
        >
          ↓
        </button>
      </>
    )

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
                    onClick={() => add({ parent: null })}
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
   *
   * **Дата — ссылка на занятие.** Строка плана отвечает «что проходим», а
   * занятие — «как оно прошло»: журнал, работы, отмена. Раньше из плана в
   * занятие пути не было вовсе, хотя обратный (со страницы занятия в план)
   * мы завели давно. Ведёт именно дата: она и есть то место строки, где
   * речь заходит о конкретном дне.
   */
  const dateCells = (node, empty = false) => {
    if (!dated) return null
    if (empty) return <span className="plan-date" />
    const slot = layout.byId.get(node.id)?.slot

    // час прошёл, а записи за ним нет: точка у даты. Не предупреждение —
    // пометка, но видно её на любой строке, и по ней сразу понятно, где
    // именно учёт прервался
    const unclosed = debts.has(slot?.id)

    return slot ? (
      <Link
        className={unclosed ? 'plan-date unclosed' : 'plan-date'}
        to={`/lesson/${slot.id}`}
        title={t(unclosed ? 'plan.unclosedHint' : 'plan.openLesson')}
      >
        {dayMonth(slot.date)} <em>{shortWeekday(slot.date)}</em>
      </Link>
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
        spotlightFor(node.id) +
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
            {moveButtons(node, false)}
            <button
              type="button"
              className="link"
              title={t('plan.insertAfter')}
              disabled={busy}
              onClick={() => add({ parent, after: node.id })}
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
        className={
          `plan-section${isTarget ? ' drop-inside' : ''}` + spotlightFor(node.id)
        }
        indicator={indicatorFor(node.id)}
        locked={locked(node)}
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
                    {moveButtons(node, true)}
                    <button
                      type="button"
                      className="link"
                      title={t('plan.addToSection')}
                      disabled={busy}
                      onClick={() => add({ parent: node.id })}
                    >
                      +
                    </button>
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
          <ul className={dated ? 'plan' : 'plan no-dates'}>
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
    </>
  )
}
