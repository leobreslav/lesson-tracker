import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { fetchScaleImpact } from './api'

/**
 * Чем оценивается работа: ничем, отметкой или по критериям.
 *
 * Три состояния, и все три — одни и те же данные: список критериев пуст,
 * в нём один безымянный, в нём несколько именованных. Отдельного «вида
 * оценивания» нет ни в базе, ни здесь; переключатель наверху только решает,
 * что показать — одно поле или список.
 *
 * Правка шкалы у работы, где оценки уже стоят, не запрещается — как и
 * правка условия, — но называет цену числом: убранный критерий уносит свои
 * оценки, и восстановить их будет неоткуда.
 */
const NONE = 'none'
const SIMPLE = 'simple'
const RUBRIC = 'rubric'

export default function ScaleDialog({ work, scale, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [mode, setMode] = useState(() => modeOf(scale))
  const [maximum, setMaximum] = useState(
    () => (scale.simple ? scale.criteria[0].maximum : 5),
  )
  const [rows, setRows] = useState(() =>
    scale.simple || !scale.criteria.length
      ? [{ name: 'A', maximum: 8 }]
      : scale.criteria.map((item) => ({ name: item.name, maximum: item.maximum })),
  )
  const [impact, setImpact] = useState(null)

  useEffect(() => {
    let current = true
    fetchScaleImpact(work)
      .then((result) => current && setImpact(result))
      .catch(() => current && setImpact(null))

    return () => {
      current = false
    }
  }, [work])

  const submit = (event) => {
    event.preventDefault()
    if (busy) return

    if (mode === NONE) return onSubmit([])
    if (mode === SIMPLE) return onSubmit([{ name: '', maximum: Number(maximum) }])

    const cleaned = rows
      .filter((row) => row.name.trim())
      .map((row) => ({ name: row.name.trim(), maximum: Number(row.maximum) }))
    return onSubmit(cleaned)
  }

  const edit = (index, field) => (event) =>
    setRows((current) =>
      current.map((row, at) =>
        at === index ? { ...row, [field]: event.target.value } : row,
      ),
    )

  return (
    <Modal onClose={onClose} title={t('grading.title')}>
      <form onSubmit={submit}>

        {impact?.marks > 0 && (
          <p className="hint warning">
            {t('grading.impact', {
              marks: impact.marks,
              students: impact.students,
            })}
          </p>
        )}

        <div className="row">
          {[NONE, SIMPLE, RUBRIC].map((option) => (
            <button
              type="button"
              key={option}
              className={mode === option ? 'chip active' : 'chip'}
              onClick={() => setMode(option)}
            >
              {t(`grading.mode.${option}`)}
            </button>
          ))}
        </div>

        {mode === SIMPLE && (
          <label className="field-with-hint">
            {t('grading.maximum')}
            <input
              type="number"
              min={1}
              max={100}
              value={maximum}
              disabled={busy}
              onChange={(event) => setMaximum(event.target.value)}
            />
          </label>
        )}

        {mode === RUBRIC && (
          <>
            <ul className="criteria">
              {rows.map((row, index) => (
                // индекс ключом намеренно: строки различаются только местом
                // в списке, и порядок здесь и есть их опознание
                <li className="row" key={index}>
                  <input
                    value={row.name}
                    maxLength={100}
                    placeholder={t('grading.criterionName')}
                    disabled={busy}
                    onChange={edit(index, 'name')}
                  />
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={row.maximum}
                    aria-label={t('grading.maximum')}
                    disabled={busy}
                    onChange={edit(index, 'maximum')}
                  />
                  <button
                    type="button"
                    className="link"
                    aria-label={t('common.delete')}
                    disabled={busy}
                    onClick={() =>
                      setRows((current) => current.filter((_, at) => at !== index))
                    }
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="secondary compact"
              disabled={busy || rows.length >= 12}
              onClick={() =>
                setRows((current) => [...current, { name: '', maximum: 8 }])
              }
            >
              {t('grading.addCriterion')}
            </button>
          </>
        )}

        <p className="hint">{t(`grading.hint.${mode}`)}</p>

        <div className="actions">
          <button type="submit" disabled={busy}>
            {t('common.save')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function modeOf(scale) {
  if (!scale.graded) return NONE
  return scale.simple ? SIMPLE : RUBRIC
}
