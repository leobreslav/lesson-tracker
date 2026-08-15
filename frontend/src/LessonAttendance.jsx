import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchAttendance, markAttendance } from './api'

const STATES = ['present', 'absent', 'late']

/**
 * Журнал занятия: кто был, кого не было, кто опоздал.
 *
 * Первым блоком на странице урока, потому что первым это и делают — до
 * того, как начали. Список строится по составу курса, а не по отметкам:
 * пока никого не отметили, строк в базе нет вовсе, и «не отмечен»
 * отличается от «не был» именно этим.
 *
 * Три кнопки в строке, а не выпадающий список: на двадцати учениках список
 * это двадцать открываний, а отметка ставится взглядом. Повторное нажатие
 * снимает — тот же приём, что у вердикта в проверке работ, и по той же
 * причине: третья кнопка «снять» была бы подписью под движением, которое
 * человек делает сам.
 *
 * Отметки уходят по одной и сразу: журнал, ждущий кнопки «сохранить», — это
 * журнал, который однажды не сохранят.
 */
export default function LessonAttendance({ slotId, may, onError }) {
  const { t } = useTranslation()
  const [students, setStudents] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(
    () =>
      fetchAttendance(slotId)
        .then((answer) => setStudents(answer.students))
        .catch(onError),
    [slotId, onError],
  )

  useEffect(() => {
    setStudents(null)
    load()
  }, [load])

  const set = async (student, status) => {
    setBusy(true)
    // рисуем сразу: отметка — движение на ходу, и ждать ответа некогда
    setStudents((current) =>
      current.map((row) => (row.id === student ? { ...row, status } : row)),
    )
    try {
      await markAttendance(slotId, [{ student, status }])
    } catch (error) {
      onError(error)
      await load()
    } finally {
      setBusy(false)
    }
  }

  if (students === null) return <p className="hint">{t('common.loading')}</p>
  if (!students.length) return <p className="hint">{t('lessonScreen.noStudents')}</p>

  const marked = students.filter((row) => row.status).length

  return (
    <>
      <p className="hint">
        {t('lessonScreen.markedCount', { marked, total: students.length })}
      </p>

      <ul className="attendance">
        {students.map((row) => (
          <li key={row.id} data-student={row.id} className={row.status ?? 'unmarked'}>
            <span className="name">
              {row.name}
              {!row.active && (
                <span className="hint"> · {t('lessonScreen.removedStudent')}</span>
              )}
            </span>

            <span className="marks">
              {STATES.map((state) => (
                <button
                  type="button"
                  key={state}
                  disabled={!may || busy}
                  aria-pressed={row.status === state}
                  className={row.status === state ? `chip active ${state}` : 'chip'}
                  onClick={() => set(row.id, row.status === state ? null : state)}
                >
                  {t(`lessonScreen.${state}`)}
                </button>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}
