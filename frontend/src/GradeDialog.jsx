import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'

/**
 * Оценка одного ученика: весь набор критериев и слова учителя разом.
 *
 * По одному критерию не ставят: у MYP их четыре, и выставляются они за один
 * взгляд на работу. Комментарий здесь же и живёт без оценки — работа может
 * не оцениваться вовсе, а сказать о ней есть что.
 *
 * Пустое поле значит «снять отметку», а не ноль: ноль — это оценка, и
 * различать их обязательно.
 */
export default function GradeDialog({ student, criteria, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [marks, setMarks] = useState(() =>
    Object.fromEntries(
      criteria.map((item) => [item.id, String(student.marks[item.id] ?? '')]),
    ),
  )
  const [comment, setComment] = useState(student.comment ?? '')

  const simple = criteria.length === 1 && !criteria[0].name

  const submit = (event) => {
    event.preventDefault()
    if (busy) return

    onSubmit({
      student: student.id,
      comment,
      marks: Object.fromEntries(
        criteria.map((item) => [
          item.id,
          marks[item.id] === '' ? null : Number(marks[item.id]),
        ]),
      ),
    })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h3>{student.name}</h3>

        {criteria.map((item) => (
          <label className="field-with-hint" key={item.id}>
            {simple
              ? t('grading.markOf', { maximum: item.maximum })
              : `${item.name} · 0–${item.maximum}`}
            <input
              type="number"
              min={0}
              max={item.maximum}
              value={marks[item.id]}
              disabled={busy}
              onChange={(event) =>
                setMarks((current) => ({ ...current, [item.id]: event.target.value }))
              }
            />
          </label>
        ))}

        <label className="field-with-hint">
          {t('grading.comment')}
          <textarea
            rows={3}
            value={comment}
            disabled={busy}
            onChange={(event) => setComment(event.target.value)}
          />
        </label>

        {criteria.length > 0 && <p className="hint">{t('grading.emptyClears')}</p>}

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
