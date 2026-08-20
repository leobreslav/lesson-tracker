import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import Switch from './Switch'
import { addFromBank, assembleWork, fetchCourseSlots, fetchCourses, fetchWorks } from './api'
import { shortDate } from './dates'
import { lastChoice, rememberChoice } from './remember'

/**
 * Объявить отобранные задачи работой.
 *
 * Три вопроса, и все три спрашиваются, потому что ни на один нет умолчания,
 * которое было бы правдой чаще, чем ложью: **какой курс** (их у учителя
 * пятнадцать), **новая работа или дописать в готовую** (набирают обычно
 * контрольную по частям) и **на каком занятии задали**.
 *
 * Занятие необязательно: контрольная за четверть, пересдача и работа «на
 * неделю» ни к какому часу не привязаны. Список часов поэтому короткий —
 * две недели вокруг сегодня: работу задают на ближайшем уроке, а не на
 * октябрьском.
 */
export default function AssembleDialog({ problems, onClose, onDone }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState([])
  const [course, setCourse] = useState(lastChoice('course'))
  const [mode, setMode] = useState('new')
  const [title, setTitle] = useState('')
  const [homework, setHomework] = useState(false)
  const [slots, setSlots] = useState([])
  const [slot, setSlot] = useState('')
  const [works, setWorks] = useState([])
  const [work, setWork] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list)
        setCourse((now) => (list.some((one) => one.id === now) ? now : list[0]?.id))
      })
      .catch((problem) => setError(problem.message))
  }, [])

  useEffect(() => {
    if (!course) return
    const today = new Date()
    const from = new Date(today)
    from.setDate(from.getDate() - 14)
    const till = new Date(today)
    till.setDate(till.getDate() + 14)

    fetchCourseSlots(course, { start: iso(from), end: iso(till) })
      .then((list) => setSlots(list.filter((one) => !one.is_cancelled)))
      .catch(() => setSlots([]))
    fetchWorks(course)
      .then((list) => {
        setWorks(list)
        setWork(String(list[0]?.id || ''))
      })
      .catch(() => setWorks([]))
  }, [course])

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'new') {
        const made = await assembleWork({
          course,
          title,
          problems,
          slot: slot ? Number(slot) : null,
          is_homework: homework,
        })
        rememberChoice('course', course)
        onDone(made)
      } else {
        await addFromBank(Number(work), problems)
        onDone({ id: Number(work) })
      }
    } catch (trouble) {
      setError(trouble.message)
      setBusy(false)
    }
  }

  return (
    <Modal title={t('bank.assemble.title', { count: problems.length })} onClose={onClose}>
      {error && <p className="error">{error}</p>}

      <label className="field">
        <span>{t('bank.assemble.course')}</span>
        <select value={course || ''} onChange={(event) => setCourse(Number(event.target.value))}>
          {courses.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
      </label>

      <Switch
        value={mode}
        label={t('bank.assemble.where')}
        options={[
          { value: 'new', label: t('bank.assemble.newWork') },
          { value: 'existing', label: t('bank.assemble.existing') },
        ]}
        onChange={setMode}
      />

      {mode === 'new' ? (
        <>
          <label className="field">
            <span>{t('bank.assemble.name')}</span>
            <input
              value={title}
              placeholder={t('bank.assemble.namePlaceholder')}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>

          <label className="field">
            <span>{t('bank.assemble.lesson')}</span>
            <select value={slot} onChange={(event) => setSlot(event.target.value)}>
              <option value="">{t('bank.assemble.noLesson')}</option>
              {slots.map((one) => (
                <option key={one.id} value={one.id}>
                  {shortDate(one.date)} · {t('bank.assemble.number', { number: one.lesson_number })}
                </option>
              ))}
            </select>
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={homework}
              onChange={(event) => setHomework(event.target.checked)}
            />
            <span>{t('bank.assemble.homework')}</span>
          </label>
        </>
      ) : works.length === 0 ? (
        // Работ в курсе ещё нет: сказать это словами дешевле, чем показать
        // пустой селект, который читается как поломка.
        <p className="hint">{t('bank.assemble.noWorks')}</p>
      ) : (
        <label className="field">
          <span>{t('bank.assemble.which')}</span>
          <select value={work} onChange={(event) => setWork(event.target.value)}>
            {works.map((one) => (
              <option key={one.id} value={one.id}>
                {one.title}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="row">
        <button
          type="button"
          onClick={send}
          disabled={busy || !course || (mode === 'existing' && !work)}
        >
          {t('bank.assemble.do')}
        </button>
        <button type="button" className="link" onClick={onClose}>
          {t('common.cancel')}
        </button>
      </div>
    </Modal>
  )
}

const iso = (date) => date.toISOString().slice(0, 10)
