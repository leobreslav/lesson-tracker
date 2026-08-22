import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import ProblemPicker from './ProblemPicker'
import { takeIntoCell } from './api'

/**
 * Накатить на ячейку готовое условие из банка.
 *
 * Не то же, что «дописать задачи из банка»: там они встают в конец, а тут
 * названо **место**. Случай обычный — работу собрали пустыми ячейками, потому
 * что условия были на бумаге, а потом третью заполнили из каталога.
 *
 * Про вердикты сказано заранее: ответы учеников — их слова и остаются, а
 * вердикт был суждением об ответе на **тот** вопрос и после подмены ни о чём.
 */
export default function CellDialogBank({ task, answered, onClose, onDone }) {
  const { t } = useTranslation()
  const [error, setError] = useState(null)

  const take = async (problem) => {
    try {
      await takeIntoCell(task.id, problem ? problem.id : null)
      onDone()
    } catch (trouble) {
      setError(trouble.message)
    }
  }

  return (
    <Modal
      title={t('works.task.fromBank', { number: task.name })}
      onClose={onClose}
    >
      {error && <p className="error">{error}</p>}
      {answered > 0 && (
        <p className="hint warning">{t('works.task.swapCost', { count: answered })}</p>
      )}

      <ProblemPicker pick={t('works.task.putHere')} onPick={take} />

      {task.problem && (
        <div className="row">
          <button type="button" className="secondary" onClick={() => take(null)}>
            {t('works.task.empty')}
          </button>
        </div>
      )}
    </Modal>
  )
}
