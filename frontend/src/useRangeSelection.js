import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Выделение диапазона дней протягиванием мыши.
 *
 * Одиночный клик диапазоном не считается: mouseup над другой ячейкой не
 * порождает click, поэтому onClick ячейки и это выделение не конфликтуют.
 * Обработчик mouseup висит на window постоянно и читает состояние из ref —
 * если подписываться в эффекте по состоянию, быстрый клик успевает пройти
 * до подписки и выделение залипает.
 */
export default function useRangeSelection({ onSelectRange, disabled }) {
  const [drag, setDrag] = useState(null) // {from, to} — обе даты в формате ISO
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

    // кнопку могут отпустить и за пределами сетки
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
