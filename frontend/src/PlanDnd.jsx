import { useDroppable } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

/** Идентификатор узла в терминах dnd-kit. */
export const dragId = (id) => `node-${id}`
export const emptyZoneId = (sectionId) => `empty-${sectionId}`

/**
 * Строка плана, которую можно перетащить.
 *
 * Ручка отдаётся наружу через children-функцию: у папки она живёт в шапке,
 * у урока — в начале строки. Тянуть можно только за ручку — иначе клики по
 * названию и кнопкам конфликтовали бы с перетаскиванием, а на телефоне
 * пропала бы прокрутка списка.
 */
export function SortableRow({ id, className = '', indicator, children }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Translate.toString(transform),
    transition,
  }

  const handle = (
    <button
      type="button"
      className="link handle"
      ref={setActivatorNodeRef}
      title="Перетащить"
      aria-label="Перетащить"
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

/** Зона сброса для пустой папки — иначе в неё нечем попасть. */
export function EmptyDropZone({ sectionId, active }) {
  const { setNodeRef } = useDroppable({ id: emptyZoneId(sectionId) })

  return (
    <li
      ref={setNodeRef}
      className={active ? 'plan-empty-zone over' : 'plan-empty-zone'}
    >
      Перетащите урок сюда
    </li>
  )
}
