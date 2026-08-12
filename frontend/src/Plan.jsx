import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import ImportDialog from './ImportDialog'
import Modal from './Modal'
import { EmptyDropZone, SortableRow, dragId, emptyZoneId } from './PlanDnd'
import {
  applyMove,
  countBlocks,
  planRows,
  pluralLessons,
  resolveDropTarget,
} from './planLogic'
import {
  createPlanNode,
  deletePlanNode,
  downloadPlanCsv,
  fetchClasses,
  fetchPlan,
  fetchSchoolYears,
  importPlanCsv,
  movePlanNode,
  movePlanNodeTo,
  movePlanSection,
  updatePlanNode,
} from './api'

const DND_INSTRUCTIONS = {
  draggable:
    'Нажмите пробел, чтобы взять элемент. Стрелками вверх и вниз выберите ' +
    'новое место, пробелом отпустите, Escape отменит перенос. То же самое ' +
    'делают кнопки со стрелками в строке.',
}

export default function Plan({ onLoggedOut }) {
  const navigate = useNavigate()
  const [classes, setClasses] = useState(null)
  const [years, setYears] = useState([])
  const [classId, setClassId] = useState(null)
  const [data, setData] = useState(null) // {nodes, counts}

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // {id, title, note}
  const [adding, setAdding] = useState(null) // {parent, after, is_section, title}
  const [deleting, setDeleting] = useState(null) // папка, которую сносим
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState(null)
  const [collapsed, setCollapsed] = useState(() => new Set())

  const [dragged, setDragged] = useState(null) // {node} — что тащим сейчас
  const [drop, setDrop] = useState(null) // {overId, side, parent, index}
  // узлы, чей перенос ещё не подтверждён сервером: повторный сброс игнорируем
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

    Promise.all([fetchClasses(), fetchSchoolYears()])
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

  /** Любая правка структуры: сделать и перечитать дерево целиком. */
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

  // --- перетаскивание ---

  const sensors = useSensors(
    // небольшой сдвиг мышью, иначе клик по названию считался бы перетаскиванием
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    // задержка на тач: без неё прокрутка списка пальцем превращается в drag
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 6 },
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  /** Вложенные droppable: сначала спрашиваем, что под курсором. */
  const collisionDetection = useCallback((args) => {
    const withinPointer = pointerWithin(args)
    // у клавиатурного перетаскивания курсора нет — там работает closestCenter
    return withinPointer.length ? withinPointer : closestCenter(args)
  }, [])

  /** Счётчики блоков считаются из уже загруженного дерева, без запросов. */
  const blocks = useMemo(
    () => countBlocks(planRows(data?.nodes ?? [])),
    [data],
  )

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

  /** Ниже ли середины наведённого элемента находится перетаскиваемый. */
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
   * Один запрос на завершённое перетаскивание.
   *
   * Дерево перестраивается сразу, кнопки не блокируются: пока запрос летит,
   * можно тащить другой узел. Повторный сброс того же узла игнорируется,
   * иначе сервер получил бы два переноса из одного исходного состояния.
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
      // перечитываем, только когда все переносы отгремели
      if (!pending.current.size) load(classId).catch(handleError)
    }
  }

  const yearById = useMemo(
    () => new Map(years.map((year) => [year.id, year])),
    [years],
  )

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

  // --- правка ---

  const startEdit = (node) =>
    setEditing({
      id: node.id,
      title: node.title,
      note: node.note,
      is_section: node.is_section,
    })

  const submitEdit = (event) => {
    event.preventDefault()
    const { id, title, note, is_section } = editing
    setEditing(null)

    if (!title.trim()) return
    const fields = is_section
      ? { title: title.trim() }
      : { title: title.trim(), note }

    run(() => updatePlanNode(id, fields))
  }

  const editKeyDown = (event) => {
    if (event.key === 'Escape') setEditing(null)
  }

  // --- добавление ---

  const openAdd = (options) => {
    setEditing(null)
    setAdding({ title: '', parent: null, after: null, is_section: false, ...options })
  }

  const submitAdd = async (event) => {
    event.preventDefault()
    const { title, parent, after, is_section } = adding
    if (!title.trim()) return

    // при вставке «после строки» форму закрываем, иначе следующий узел
    // встал бы перед только что созданным
    if (after) setAdding(null)
    else setAdding({ ...adding, title: '' })

    await run(() =>
      createPlanNode({
        school_class: classId,
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
      const result = await importPlanCsv(classId, file, mode)
      await load(classId)
      setNotice(
        `Создано строк: ${result.created_rows} ` +
          `(тем ${result.created_headers}, уроков ${result.created_lessons}).` +
          (result.warnings.length
            ? ` Пропущено: ${result.warnings.length}. ${result.warnings.join(' ')}`
            : ''),
      )
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const handleExport = async () => {
    setError(null)
    try {
      await downloadPlanCsv(classId)
    } catch (err) {
      handleError(err)
    }
  }

  // --- удаление ---

  const removeLesson = (node) => {
    if (!window.confirm(`Удалить «${node.title}»?`)) return
    run(() => deletePlanNode(node.id, true))
  }

  const removeSection = (keepChildren) => {
    const section = deleting
    setDeleting(null)
    run(() => deletePlanNode(section.id, keepChildren))
  }

  // --- отрисовка ---

  const editForm = (node) => (
    <form className="plan-edit" onSubmit={submitEdit}>
      <input
        autoFocus
        value={editing.title}
        maxLength={200}
        aria-label="Название"
        onChange={(event) => setEditing({ ...editing, title: event.target.value })}
        onKeyDown={editKeyDown}
      />
      {!node.is_section && (
        <>
          <input
            value={editing.note}
            maxLength={500}
            placeholder="заметка"
            aria-label="Заметка"
            onChange={(event) => setEditing({ ...editing, note: event.target.value })}
            onKeyDown={editKeyDown}
          />
        </>
      )}
      <button type="submit" disabled={busy}>
        Сохранить
      </button>
      <button type="button" className="secondary" onClick={() => setEditing(null)}>
        Отмена
      </button>
    </form>
  )

  const addForm = () => (
    <form className="plan-add-form" onSubmit={submitAdd}>
      <input
        autoFocus
        value={adding.title}
        maxLength={200}
        placeholder={adding.is_section ? 'Название папки' : 'Название урока'}
        aria-label="Название"
        onChange={(event) => setAdding({ ...adding, title: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setAdding(null)
        }}
      />
      <button type="submit" disabled={busy || !adding.title.trim()}>
        Добавить
      </button>
      <button type="button" className="secondary" onClick={() => setAdding(null)}>
        Готово
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
        title="Выше"
        disabled={busy}
        onClick={() => run(() => mover(node.id, 'up'))}
      >
        ↑
      </button>
      <button
        type="button"
        className="link"
        title="Ниже"
        disabled={busy}
        onClick={() => run(() => mover(node.id, 'down'))}
      >
        ↓
      </button>
    </>
  )

  const indicatorFor = (id) => (drop?.overId === dragId(id) ? drop.side : null)

  const renderLesson = (node, parent) => (
    <SortableRow
      key={node.id}
      id={dragId(node.id)}
      className="plan-row lesson"
      indicator={indicatorFor(node.id)}
    >
      {(handle) =>
        editing?.id === node.id ? (
        <>
          {handle}
          <span className="plan-number">{node.number}</span>
          {editForm(node)}
        </>
      ) : (
        <>
          {handle}
          <span className="plan-number">{node.number}</span>
          <button
            type="button"
            className="link title"
            title="Переименовать"
            disabled={busy}
            onClick={() => startEdit(node)}
          >
            {node.title}
          </button>
          {node.note && <span className="hint">{node.note}</span>}

          <span className="row-actions">
            {moveButtons(node, movePlanNode)}
            <button
              type="button"
              className="link"
              title="Вставить урок после"
              disabled={busy}
              onClick={() => openAdd({ parent, after: node.id })}
            >
              +
            </button>
            <button
              type="button"
              className="link"
              title="Удалить"
              disabled={busy}
              onClick={() => removeLesson(node)}
            >
              ✕
            </button>
          </span>
        </>
        )
      }
    </SortableRow>
  )

  const renderSection = (node) => {
    const hidden = collapsed.has(node.id)
    const childIds = node.children.map((child) => dragId(child.id))
    // папка подсвечивается, когда урок наведён на неё как на контейнер
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
        <div className="plan-row section-head">
          {handle}
          <button
            type="button"
            className="link toggle"
            title={hidden ? 'Развернуть' : 'Свернуть'}
            onClick={() => toggleSection(node.id)}
          >
            {hidden ? '▸' : '▾'}
          </button>

          {editing?.id === node.id ? (
            editForm(node)
          ) : (
            <>
              <button
                type="button"
                className="link title"
                title="Переименовать"
                disabled={busy}
                onClick={() => startEdit(node)}
              >
                {node.title}
              </button>
              <span className="hint block-count">
                {pluralLessons(blocks.byId.get(node.id)?.lessons ?? 0)}
              </span>

              <span className="row-actions">
                {moveButtons(node, movePlanSection)}
                <button
                  type="button"
                  className="link"
                  title="Добавить урок в папку"
                  disabled={busy}
                  onClick={() => openAdd({ parent: node.id })}
                >
                  +
                </button>
                <button
                  type="button"
                  className="link"
                  title="Удалить папку"
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
              {node.children.map((child) => (
                <Fragment key={child.id}>
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
      <main className="page narrow">
        <p>{error ? <span className="error">{error}</span> : 'Загрузка…'}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>Учебный план</h1>
      </header>

      {!classes.length ? (
        <div className="panel">
          <p>План составляется для класса, а классов пока нет.</p>
          <button type="button" onClick={() => navigate('/classes')}>
            Завести класс
          </button>
        </div>
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
            <p className="hint plan-counts">
              Уроков: <strong>{data.counts.lessons}</strong>. Папок:{' '}
              {data.counts.sections}.
              {blocks.loose > 0 && <> Вне блоков: {blocks.loose}.</>}
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
            <p>Загрузка…</p>
          ) : (
            <>
              <DndContext
                sensors={sensors}
                collisionDetection={collisionDetection}
                accessibility={{ screenReaderInstructions: DND_INSTRUCTIONS }}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragEnd={handleDragEnd}
                onDragCancel={handleDragCancel}
              >
                <SortableContext
                  items={data.nodes.map((node) => dragId(node.id))}
                  strategy={verticalListSortingStrategy}
                >
                  <ul className="plan">
                    {data.nodes.map((node) => (
                      <Fragment key={node.id}>
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

              {!data.nodes.length && (
                <p className="hint">
                  План пуст. Добавьте первый урок или соберите тему в папку.
                </p>
              )}

              <div className="actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => openAdd({ parent: null })}
                >
                  + урок
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => openAdd({ parent: null, is_section: true })}
                >
                  + папка
                </button>

                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => setImporting(true)}
                >
                  Импорт CSV
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={handleExport}
                >
                  Экспорт CSV
                </button>
              </div>
            </>
          )}
        </>
      )}

      {importing && (
        <ImportDialog
          busy={busy}
          onSubmit={handleImport}
          onClose={() => setImporting(false)}
        />
      )}

      {deleting && (
        <Modal onClose={() => setDeleting(null)}>
          <h3>Удалить папку «{deleting.title}»?</h3>
          <p className="hint">
            В ней {deleting.children.length} уроков. Их можно вынуть на верхний
            уровень — они встанут на место папки и сохранят порядок.
          </p>
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => removeSection(true)}>
              Удалить, уроки оставить
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => removeSection(false)}
            >
              Удалить вместе с уроками
            </button>
            <button type="button" className="secondary" onClick={() => setDeleting(null)}>
              Отмена
            </button>
          </div>
        </Modal>
      )}
    </main>
  )
}
