import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import { MAX_LESSON_NUMBER } from './scheduleLogic'
import { fetchBells, saveBells } from './api'

/**
 * Расписание звонков: во сколько начинается и кончается каждый урок.
 *
 * Правится **целиком**, одной кнопкой: это одна вещь, а не десять
 * независимых строк, и номер урока в ней ключ. Построчное сохранение
 * потребовало бы отдельного разговора про удаление там, где удаляют ровно
 * тогда, когда школа сократила день, — а сокращают его сразу, а не по уроку.
 *
 * Показываются **все** номера до максимума, а не только заполненные. Пустая
 * строка значит «этого урока в школе нет», и увидеть, где кончается день,
 * можно только рядом с пустыми: список из шести строк не отвечает на вопрос,
 * бывает ли седьмой.
 *
 * Заполнено может быть не всё, и это не незаконченная настройка: до звонков
 * школа жила, сетка показывала номера — и покажет, если строку стереть.
 */
// Права здесь не спрашиваются: раздел «Справочники» и так открыт
// администратору, а отказ не-администратору приходит с сервера кодом — как у
// систем оценивания и параллелей рядом. Второй ответ на тот же вопрос в
// браузере разошёлся бы с первым.
export default function BellsPanel() {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchBells()
      .then((answer) => {
        if (cancelled) return
        const known = Object.fromEntries(
          answer.bells.map((bell) => [bell.number, bell]),
        )
        setRows(
          Array.from({ length: MAX_LESSON_NUMBER }, (_, index) => ({
            number: index + 1,
            starts_at: known[index + 1]?.starts_at ?? '',
            ends_at: known[index + 1]?.ends_at ?? '',
          })),
        )
      })
      .catch((err) => !cancelled && setError(err.message))

    return () => {
      cancelled = true
    }
  }, [])

  const set = (number, field, value) => {
    setSaved(false)
    setRows((current) =>
      current.map((row) => (row.number === number ? { ...row, [field]: value } : row)),
    )
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      // наверх уезжают только заполненные строки: пустая — это «такого урока
      // нет», а не «время не указали», и сервер о ней знать не должен
      await saveBells(rows.filter((row) => row.starts_at && row.ends_at))
      setSaved(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (rows === null) {
    return (
      <section className="panel">
        <h3>{t('bells.title')}</h3>
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h3>{t('bells.title')}</h3>
      <Hint short={t('bells.hint')} more={t('bells.hintMore')} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <ul className="bell-list">
        {rows.map((row) => (
          <li key={row.number} className="row middle">
            <span className="bell-number">{row.number}</span>
            <input
              type="time"
              value={row.starts_at}
              disabled={busy}
              aria-label={t('bells.startsAt', { number: row.number })}
              onChange={(event) => set(row.number, 'starts_at', event.target.value)}
            />
            <span className="hint">—</span>
            <input
              type="time"
              value={row.ends_at}
              disabled={busy}
              aria-label={t('bells.endsAt', { number: row.number })}
              onChange={(event) => set(row.number, 'ends_at', event.target.value)}
            />
          </li>
        ))}
      </ul>

      <div className="actions">
        <button type="button" disabled={busy} onClick={save}>
          {t('common.save')}
        </button>
        {saved && <span className="hint">{t('bells.saved')}</span>}
      </div>
    </section>
  )
}
