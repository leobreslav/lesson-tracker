import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { deleteAttachment, gradeStudent, openAttachment, uploadAttachment } from './api'
import { formatSize, iconFor } from './fileKind'

/**
 * Работа одного ученика: скан, оценка и слова учителя — в одном окне.
 *
 * Это и есть строка «работа и ученик», показанная целиком. Раньше её не
 * было, и ученическое лежало по разным местам: ответы на отправках, а скану
 * и оценке жить было негде.
 *
 * Оценки ставятся всем набором сразу: у MYP критериев четыре, и
 * выставляются они за один взгляд на работу. Пустое поле снимает отметку, а
 * не ставит ноль — ноль это оценка, и различать их обязательно.
 *
 * Скан применяется **сразу**, а оценка и комментарий ждут «Сохранить». Так
 * же, как в панели урока: файл, ждущий кнопки, — это загрузка, которая тихо
 * не случилась.
 */
export default function GradeDialog({
  work,
  student,
  criteria,
  tasks = [],
  busy,
  onSubmit,
  onChanged,
  onClose,
}) {
  const { t } = useTranslation()
  const [marks, setMarks] = useState(() =>
    Object.fromEntries(
      criteria.map((item) => [item.id, String(student.marks[item.id] ?? '')]),
    ),
  )
  /*
   * Баллы за вопросы — вторая ось, и правятся они здесь по одной причине:
   * иначе их негде править вовсе. Ставит их либо проверка ответа, либо
   * разбор скана, и ошибку чтения — «модель увидела 8 вместо 3» — чинить
   * было нечем.
   */
  const [scores, setScores] = useState(() =>
    Object.fromEntries(
      tasks.map((item) => [item.id, String(student.scores?.[item.id] ?? '')]),
    ),
  )
  const [comment, setComment] = useState(student.comment ?? '')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

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
      // пустое поле снимает балл, а не ставит ноль: ноль — это оценка, и
      // различать их обязательно, как и у критериев
      scores: Object.fromEntries(
        tasks.map((item) => [
          item.id,
          scores[item.id] === '' ? null : Number(scores[item.id]),
        ]),
      ),
    })
  }

  /**
   * Строка «работа и ученик» заводится по требованию, и скану нужен её id.
   * Пустой вызов оценки её создаёт и ничего не меняет — то самое «по
   * требованию» и есть.
   */
  const upload = async (file) => {
    if (!file) return

    setUploading(true)
    setError(null)
    try {
      const row = student.row ?? (await gradeStudent(work, { student: student.id })).id
      await uploadAttachment({ studentWork: row, file })
      await onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const remove = async (paper) => {
    setUploading(true)
    try {
      await deleteAttachment(paper.id)
      await onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const papers = student.papers ?? []

  return (
    <Modal onClose={onClose} title={student.name}>
      <form onSubmit={submit}>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {/* приложить работу можно к любой: класс писал онлайн, а сдал на
            бумаге — обычный случай, и раньше его запирал флаг */}
        <section className="papers">
            <span className="hint">{t('paper.scans')}</span>
            <ul className="attachments">
              {papers.map((paper) => {
                const size = formatSize(paper.size)

                return (
                  <li key={paper.id} className="attachment">
                    <span className="attachment-icon" aria-hidden="true">
                      {iconFor(paper)}
                    </span>
                    {paper.kind === 'link' ? (
                      <a
                        href={paper.url}
                        target="_blank"
                        rel="noreferrer"
                        className="title"
                      >
                        {paper.title}
                      </a>
                    ) : (
                      <button
                        type="button"
                        className="link title"
                        onClick={() => openAttachment(paper.id)}
                      >
                        {paper.title}
                      </button>
                    )}
                    {size && (
                      <span className="hint">
                        {t(`lesson.size.${size.unit}`, { value: size.value })}
                      </span>
                    )}
                    <button
                      type="button"
                      className="link remove"
                      title={t('common.delete')}
                      disabled={busy || uploading}
                      onClick={() => remove(paper)}
                    >
                      ✕
                    </button>
                  </li>
                )
              })}
            </ul>
            <div className="row">
              <input
                type="file"
                aria-label={t('paper.addScan')}
                disabled={busy || uploading}
                onChange={(event) => {
                  upload(event.target.files?.[0])
                  event.target.value = ''
                }}
              />
            </div>
          </section>

        {tasks.length > 0 && (
          <section className="panel">
            <p className="hint">{t('grading.questionScores')}</p>
            <div className="score-row">
              {tasks.map((item) => (
                <label className="field-with-hint" key={item.id}>
                  {`${item.name} · 0–${item.maximum}`}
                  <input
                    type="number"
                    min={0}
                    max={item.maximum}
                    value={scores[item.id]}
                    disabled={busy}
                    onChange={(event) =>
                      setScores((current) => ({
                        ...current,
                        [item.id]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          </section>
        )}

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
        </div>
      </form>
    </Modal>
  )
}
