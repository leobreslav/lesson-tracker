import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { remember, remembered } from './remember'

/**
 * Показывать ли в списке класса тех, кто с курса снят.
 *
 * Снятый остаётся строкой, и это решение, а не недосмотр: его оценки и
 * ответы никуда не делись, и «почему у него пусто в декабре» спрашивать
 * будут о нём же. Но решение это про **данные**, а не про экран. Класс, из
 * которого за год ушло шестеро, показывал шесть серых строк вперемешку с
 * работающими, и искать глазами живого ученика приходилось через них —
 * каждый день, хотя нужны ушедшие раз в четверть.
 *
 * Поэтому показ — по требованию, и помнится он между заходами: кому
 * снятые мешают, мешают всегда. Ключ **один на таблицу результатов и
 * журнал**: вопрос у них общий, «кого я считаю классом», и два разных
 * ответа на соседних экранах читались бы как расхождение в данных.
 *
 * Умолчание — показывать. До появления переключателя снятые были видны
 * всегда, и спрятать их молча значило бы, что у кого-то пропали строки с
 * оценками, а причины он не знает.
 *
 * Скрытое при этом только скрыто: сводки над таблицей считает сервер, и
 * числа в них от переключателя не зависят.
 */
const KEY = 'showRemovedStudents'

export function useShowRemoved() {
  const [shown, setShown] = useState(() => remembered(KEY, true))

  const set = (value) => {
    setShown(value)
    remember(KEY, value)
  }

  return [shown, set]
}

/** Строки, которые показывать: все или только тех, кто сейчас в курсе. */
export const visibleStudents = (students, shown) =>
  shown ? students : students.filter((row) => row.active !== false)

export default function RemovedToggle({ students, shown, onChange }) {
  const { t } = useTranslation()
  const removed = students.filter((row) => row.active === false).length

  // некого прятать — нечего и спрашивать: переключатель, который ничего не
  // меняет на экране, читается как сломанный
  if (!removed) return null

  return (
    <label className="checkbox removed-toggle">
      <input
        type="checkbox"
        checked={shown}
        onChange={(event) => onChange(event.target.checked)}
      />
      {t('table.showRemoved', { count: removed })}
    </label>
  )
}
