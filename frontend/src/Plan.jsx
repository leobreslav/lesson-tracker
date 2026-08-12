import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
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
import Modal from './Modal'
import { EmptyDropZone, SortableRow, dragId, emptyZoneId } from './PlanDnd'
import {
  applyMove,
  countBlocks,
  planRows,
  resolveDropTarget,
} from './planLogic'
import {
  createPlanNode,
  deletePlanNode,
  downloadPlanCsv,
  fetchCourses,
  fetchPlan,
  fetchSchoolYears,
  importPlanCsv,
  movePlanNode,
  movePlanNodeTo,
  movePlanSection,
  updatePlanNode,
} from './api'

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
  const [editing, setEditing] = useState(null) // {id, title, note}
  const [adding, setAdding] = useState(null) // {parent, after, is_section, title}
  const [deleting, setDeleting] = useState(null) // the section being removed
  const [importing, setImporting] = useState(false)
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
      const result = await importPlanCsv(classId, file, mode)
      await load(classId)
      setNotice(
        t('plan.imported', {
          rows: result.created_rows,
          sections: result.created_headers,
          lessons: result.created_lessons,
        }) +
          (result.warnings.length
            ? t('plan.importedSkipped', {
                count: result.warnings.length,
                details: result.warnings
                  .map((warning) => t(`warnings.${warning.code}`, warning.params))
                  .join(' '),
              })
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

  const editForm = (node) => (
    <form className="plan-edit" onSubmit={submitEdit}>
      <input
        autoFocus
        value={editing.title}
        maxLength={200}
        aria-label={t('plan.titleLabel')}
        onChange={(event) => setEditing({ ...editing, title: event.target.value })}
        onKeyDown={editKeyDown}
      />
      {!node.is_section && (
        <>
          <input
            value={editing.note}
            maxLength={500}
            placeholder={t('plan.notePlaceholder')}
            aria-label={t('plan.noteLabel')}
            onChange={(event) => setEditing({ ...editing, note: event.target.value })}
            onKeyDown={editKeyDown}
          />
        </>
      )}
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
            title={t('plan.rename')}
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
        )
      }
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
        <div className="plan-row section-head">
          {handle}
          <button
            type="button"
            className="link toggle"
            title={t(hidden ? 'plan.expand' : 'plan.collapse')}
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
                title={t('plan.rename')}
                disabled={busy}
                onClick={() => startEdit(node)}
              >
                {node.title}
              </button>
              <span className="hint block-count">
                {t('common.lessonCount', {
                  count: blocks.byId.get(node.id)?.lessons ?? 0,
                })}
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
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
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
            <p className="hint plan-counts">
              <Trans
                i18nKey="plan.counts"
                values={{
                  lessons: data.counts.lessons,
                  sections: data.counts.sections,
                }}
              >
                <strong>{data.counts.lessons}</strong>
              </Trans>
              {blocks.loose > 0 && t('plan.loose', { count: blocks.loose })}
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
                <EmptyState title={t('plan.empty.title')}>
                  {t('plan.empty.hint')}
                </EmptyState>
              )}

              <div className="actions">
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

                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => setImporting(true)}
                >
                  {t('plan.importCsv')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={handleExport}
                >
                  {t('plan.exportCsv')}
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
