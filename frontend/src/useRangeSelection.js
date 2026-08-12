import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Selecting a range of days by dragging the mouse.
 *
 * A single click is not a range: releasing over another cell produces no
 * click there, so a cell's onClick and this selection never collide. The
 * mouseup handler sits on window permanently and reads the state from a ref —
 * subscribing inside an effect keyed on state lets a fast click slip through
 * before the subscription, and the selection sticks.
 */
export default function useRangeSelection({ onSelectRange, disabled }) {
  const [drag, setDrag] = useState(null) // {from, to}, both ISO dates
  const dragRef = useRef(null)

  const updateDrag = useCallback((value) => {
    dragRef.current = value
    setDrag(value)
  }, [])

  useEffect(() => {
    const finish = () => {
      const current = dragRef.current
      if (!current) return

      updateDrag(null)
      const [from, to] = [current.from, current.to].sort()
      if (from !== to) onSelectRange(from, to)
    }

    // the button can be released outside the grid too
    window.addEventListener('mouseup', finish)
    return () => window.removeEventListener('mouseup', finish)
  }, [onSelectRange, updateDrag])

  const dayProps = useCallback(
    (date) => ({
      onMouseDown: () => {
        if (!disabled) updateDrag({ from: date, to: date })
      },
      onMouseEnter: () => {
        if (dragRef.current) updateDrag({ ...dragRef.current, to: date })
      },
    }),
    [disabled, updateDrag],
  )

  const isSelected = useCallback(
    (date) => {
      if (!drag) return false
      const [from, to] = [drag.from, drag.to].sort()
      return from <= date && date <= to
    },
    [drag],
  )

  return { isSelected, dayProps }
}
