import { useDroppable } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useTranslation } from 'react-i18next'

/** The id of a node in dnd-kit terms. */
export const dragId = (id) => `node-${id}`
export const emptyZoneId = (sectionId) => `empty-${sectionId}`

/**
 * A plan row that can be dragged.
 *
 * The handle is handed outwards through a children function: a section keeps
 * it in its header, a lesson at the start of the row. Only the handle drags —
 * otherwise clicks on the title and the buttons would fight the drag, and on
 * a phone the list would stop scrolling.
 *
 * `locked` — проведённый урок: за ним записан час, и позиция ему больше не
 * указ. Ручка у такой строки остаётся на месте, но не тянется и объясняет
 * почему: исчезнувшая ручка читалась бы как поломка, а сервер всё равно
 * откажет (`plan_lesson_taught`). Двигается всё, что ниже последней
 * связи, — то есть будущее, ради которого перетаскивание и заведено.
 */
export function SortableRow({ id, className = '', indicator, locked = false, children }) {
  const { t } = useTranslation()
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled: locked })

  const style = {
    transform: CSS.Translate.toString(transform),
    transition,
  }

  const handle = locked ? (
    <span className="handle locked" title={t('plan.taught')} aria-hidden="true">
      ⠿
    </span>
  ) : (
    <button
      type="button"
      className="link handle"
      ref={setActivatorNodeRef}
      title={t('plan.drag')}
      aria-label={t('plan.drag')}
      {...attributes}
      {...listeners}
    >
      ⠿
    </button>
  )

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={
        `${className}` +
        (isDragging ? ' dragging' : '') +
        (indicator ? ` drop-${indicator}` : '')
      }
    >
      {children(handle)}
    </li>
  )
}

/** A drop zone for an empty section — otherwise nothing can reach inside. */
export function EmptyDropZone({ sectionId, active }) {
  const { t } = useTranslation()
  const { setNodeRef } = useDroppable({ id: emptyZoneId(sectionId) })

  return (
    <li
      ref={setNodeRef}
      className={active ? 'plan-empty-zone over' : 'plan-empty-zone'}
    >
      {t('plan.dropHere')}
    </li>
  )
}
