import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import TaskBrief from './TaskBrief'
import Verdict from './Verdict'
import { fetchSubmissions } from './api'

/**
 * Проверка столбцом: все ответы на одну задачу подряд.
 *
 * Это основной режим, а не второй. Проверяют по задачам: глаз настроен на
 * один эталон, и пятнадцать ответов на «раскройте скобки» читаются в один
 * проход, а те же пятнадцать ответов вперемешку с ответами на другие задачи
 * — нет.
 *
 * Эталоны висят рядом с условием: сверяются с ними, а не с памятью.
 * Непроверенные идут первыми — ради них сюда и заходят.
 */
export default function ColumnDialog({ task, onChanged, onClose }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(
    () => fetchSubmissions({ task: task.id }).then(setRows),
    [task.id],
  )

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  const checked = () => {
    onChanged()
    return load()
  }

  // в столбце у ученика может быть несколько попыток: проверяют последнюю,
  // прошлые открываются из ячейки
  const latest = lastPerStudent(rows ?? [])
  const waiting = latest.filter((row) => row.is_correct === null)
  const done = latest.filter((row) => row.is_correct !== null)

  return (
    <Modal className="shelf" onClose={onClose}>
      <h3>{t('table.checking')}</h3>

      <TaskBrief task={task} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {rows === null ? (
        <p>{t('common.loading')}</p>
      ) : latest.length === 0 ? (
        <p className="hint">{t('table.noAnswers')}</p>
      ) : (
        <>
          <span className="hint">
            {t('table.waiting', { count: waiting.length })}
          </span>
          <ul className="attempt-list checking">
            {[...waiting, ...done].map((row) => (
              <li key={row.id} className={verdictClass(row.is_correct)}>
                <span className="hint">{row.student_name}</span>
                <span className="answer">{row.answer}</span>
                <Verdict submission={row} onChanged={checked} onError={setError} />
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          {t('common.close')}
        </button>
      </div>
    </Modal>
  )
}

/** Последняя отправка каждого: журнал приходит по возрастанию времени. */
function lastPerStudent(rows) {
  const seen = new Map()
  rows.forEach((row) => seen.set(row.student, row))
  return [...seen.values()]
}

const verdictClass = (value) =>
  value === true ? 'correct' : value === false ? 'wrong' : 'unchecked'
