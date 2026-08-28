import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import { MAX_LESSON_NUMBER } from './scheduleLogic'
import { fetchSchoolDay, saveSchoolDay } from './api'

/**
 * Школьный день: сколько в нём уроков и во сколько каждый начинается.
 *
 * Правится **целиком**, одной кнопкой: это одна вещь, а не десять
 * независимых строк, и номер урока в ней ключ. Построчное сохранение
 * потребовало бы отдельного разговора про удаление там, где удаляют ровно
 * тогда, когда школа сократила день, — а сокращают его сразу, а не по уроку.
 *
 * **Строк ровно столько, сколько уроков в дне.** Раньше их было десять
 * всегда, а пустая значила «этого урока в школе нет»; читалось это ровно
 * наоборот — как незаполненная настройка, — и ответить на вопрос «сколько у
 * нас уроков» было нечем: молчание пустой строки ничем не отличается от
 * забытой. Теперь длина дня — число, которое школа ставит сама, а сетка
 * расписания рисует столько рядов, сколько уроков.
 *
 * **Убирается только последний урок.** Снос из середины означал бы
 * перенумерацию уже расставленных часов, а номер в этом проекте — ключ
 * занятия: перенос звонка не должен переписывать расписание. День сокращают
 * с конца, им же и удлиняют.
 *
 * **Сокращение ничего не отменяет.** Занятия, уже стоящие на снимаемых
 * номерах, остаются: иначе школа с восьмиурочным прошлым не перешла бы на
 * шесть уроков никогда. Сказано об этом словами и заранее — по числу
 * `busiest` с сервера, — потому что молчаливое «кнопка нажалась, а в сетке
 * всё по-старому» читается как поломка.
 *
 * Время при этом заполнено может быть не всё, и это не незаконченная
 * настройка: до звонков школа жила, сетка показывала номера — и покажет,
 * если строку стереть.
 */
// Права здесь не спрашиваются: раздел «Справочники» и так открыт
// администратору, а отказ не-администратору приходит с сервера кодом — как у
// систем оценивания и параллелей рядом. Второй ответ на тот же вопрос в
// браузере разошёлся бы с первым.
export default function BellsPanel() {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  // самый поздний занятый номер: не запрет, а то, о чём предупреждают
  const [busiest, setBusiest] = useState(0)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchSchoolDay()
      .then((answer) => {
        if (cancelled) return
        const known = Object.fromEntries(
          answer.bells.map((bell) => [bell.number, bell]),
        )
        setBusiest(answer.busiest)
        setRows(
          Array.from({ length: answer.lessons_per_day }, (_, index) => ({
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

  const addLesson = () => {
    setSaved(false)
    setRows((current) => [
      ...current,
      { number: current.length + 1, starts_at: '', ends_at: '' },
    ])
  }

  const removeLesson = () => {
    setSaved(false)
    setRows((current) => current.slice(0, -1))
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      // наверх уезжают только заполненные строки: пустая — это «время не
      // указали», а не отдельная сущность, и сервер о ней знать не должен.
      // Длину дня несёт само число строк — она и есть ответ на «сколько уроков»
      const answer = await saveSchoolDay({
        lessonsPerDay: rows.length,
        bells: rows.filter((row) => row.starts_at && row.ends_at),
      })
      setBusiest(answer.busiest)
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

      <div className="row middle">
        <button
          type="button"
          className="secondary"
          disabled={busy || rows.length >= MAX_LESSON_NUMBER}
          onClick={addLesson}
        >
          {t('bells.addLesson')}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || rows.length <= 1}
          onClick={removeLesson}
        >
          {t('bells.removeLesson', { number: rows.length })}
        </button>
      </div>

      {/* Предупреждение, а не отказ: занятия на снимаемых номерах остаются */}
      {rows.length < busiest && (
        <p className="hint" role="status">
          {t('bells.busiest', { number: busiest })}
        </p>
      )}

      <div className="actions">
        <button type="button" disabled={busy} onClick={save}>
          {t('common.save')}
        </button>
        {saved && <span className="hint">{t('bells.saved')}</span>}
      </div>
    </section>
  )
}
