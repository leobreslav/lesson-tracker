import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import TaskBrief from './TaskBrief'
import Verdict from './Verdict'
import { fetchSubmissions } from './api'
import { dateTime } from './dates'

/**
 * История одной ячейки: все попытки ученика по одной задаче.
 *
 * Сверху — условие и эталоны: без них проверка одной ячейки превращается в
 * «а что тут вообще спрашивали».
 *
 * Открытую ячейку опрос **не перерисовывает**: пока учитель читает ответ,
 * содержимое под курсором меняться не должно. Если ученик отправил новое,
 * окно говорит об этом строкой и кнопкой «показать» — решение остаётся за
 * учителем, а не за таймером.
 */
export default function CellDialog({ student, task, onChanged, onClose }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  const [fresh, setFresh] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(
    () =>
      fetchSubmissions({ task: task.id, student: student.id }).then((result) => {
        setRows(result)
        setFresh(false)
      }),
    [task.id, student.id],
  )

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  // проверка отсюда меняет таблицу под окном, поэтому о ней сообщаем наверх
  const checked = () => {
    onChanged()
    return load()
  }

  return (
    <Modal onClose={onClose}>
      <h3>{student.name}</h3>

      {/* что спрашивали и что считается верным: проверяя ячейку, учитель
          сверяется с эталоном, а не вспоминает его */}
      <TaskBrief task={task} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {fresh && (
        <p className="hint warning">
          {t('table.newAnswer')}{' '}
          <button type="button" className="link" onClick={() => load()}>
            {t('table.show')}
          </button>
        </p>
      )}

      {rows === null ? (
        <p>{t('common.loading')}</p>
      ) : (
        <ul className="attempt-list">
          {rows.map((row, index) => (
            <li key={row.id} className={verdictClass(row.is_correct)}>
              <span className="attempt">
                {t('student.work.attemptNumber', { number: index + 1 })}
              </span>
              <span className="answer">{row.answer}</span>
              <span className="hint">{dateTime(row.created_at)}</span>
              <Verdict submission={row} onChanged={checked} onError={setError} />
            </li>
          ))}
        </ul>
      )}

      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          {t('common.close')}
        </button>
      </div>
    </Modal>
  )
}

const verdictClass = (value) =>
  value === true ? 'correct' : value === false ? 'wrong' : 'unchecked'
