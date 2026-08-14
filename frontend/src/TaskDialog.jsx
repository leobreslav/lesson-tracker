import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Markdown from './Markdown'
import Modal from './Modal'
import { fetchTaskImpact } from './api'

/**
 * Задача: условие и список допустимых ответов.
 *
 * Ответов несколько, потому что «x+3» и «3+x» одинаково верны, и решить это
 * при проверке нельзя — учитель сверяется с эталоном глазами. Пустой список
 * законен: задача, которую всё равно читают руками.
 *
 * Условие — Markdown с формулами, как содержание урока, и рядом
 * предпросмотр: `$$…$$` в наборе выглядит одинаково, а на экране — нет.
 *
 * У задачи, по которой уже отвечали, окно называет цену правки и предлагает
 * **перепроверить** — это про неверный эталон: полкласса проверено
 * неправильно, и вердикты надо снять, не трогая ответы.
 */
export default function TaskDialog({ task, busy, onSubmit, onRecheck, onClose }) {
  const { t } = useTranslation()
  const [question, setQuestion] = useState(task?.question ?? '')
  const [answers, setAnswers] = useState(() => [...(task?.answers ?? []), ''])
  const [impact, setImpact] = useState(null)
  const [preview, setPreview] = useState(false)

  useEffect(() => {
    if (!task) return undefined

    let current = true
    fetchTaskImpact(task.id)
      .then((result) => current && setImpact(result))
      .catch(() => current && setImpact(null))

    return () => {
      current = false
    }
  }, [task])

  const setAnswer = (index, value) =>
    setAnswers((current) => {
      const next = [...current]
      next[index] = value
      // последняя строка всегда пустая: добавлять эталон кнопкой, когда
      // поле для него уже нужно, — лишнее нажатие
      if (index === next.length - 1 && value.trim()) next.push('')
      return next
    })

  const submit = (event) => {
    event.preventDefault()
    if (busy || !question.trim()) return

    onSubmit({
      question,
      answers: answers.filter((answer) => answer.trim()),
    })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h3>{t(task ? 'works.task.edit' : 'works.task.add')}</h3>

        {impact?.answers > 0 && (
          <p className="hint warning">
            {t('works.task.impact', {
              answers: impact.answers,
              checked: impact.checked,
            })}
          </p>
        )}

        <div className="row">
          <span className="hint">{t('works.task.question')}</span>
          <button
            type="button"
            className="link"
            onClick={() => setPreview((current) => !current)}
          >
            {t(preview ? 'works.task.write' : 'works.task.preview')}
          </button>
        </div>

        {preview ? (
          <div className="task-preview">
            <Markdown text={question} />
          </div>
        ) : (
          <textarea
            autoFocus
            rows={5}
            value={question}
            aria-label={t('works.task.question')}
            onChange={(event) => setQuestion(event.target.value)}
          />
        )}

        <span className="hint">{t('works.task.answers')}</span>
        <p className="hint">{t('works.task.answersHint')}</p>
        <ul className="answer-list">
          {answers.map((answer, index) => (
            // индекс как ключ намеренно: строки здесь и есть позиции, а
            // «тот же ответ на другом месте» — это другой ответ
            <li key={index}>
              <input
                value={answer}
                aria-label={t('works.task.answerNumber', { number: index + 1 })}
                onChange={(event) => setAnswer(index, event.target.value)}
              />
            </li>
          ))}
        </ul>

        <div className="actions">
          <button type="submit" disabled={busy || !question.trim()}>
            {t('common.save')}
          </button>
          {impact?.checked > 0 && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => onRecheck(task)}
            >
              {t('works.task.recheck', { count: impact.checked })}
            </button>
          )}
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
