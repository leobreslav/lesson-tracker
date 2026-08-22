import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import ProblemPicker from './ProblemPicker'
import { declareAnalogue } from './api'

/**
 * «Это аналог вот той» — то есть та же задача с другими числами.
 *
 * Ищется вторая задача тем же поиском, что и везде (`ProblemPicker`): заводить
 * ради одного окна второй способ найти условие значит завести и второе место,
 * где живут правила видимости.
 *
 * Свою же задачу в списке не показываем: «аналог самого себя» сервер отклонит,
 * а строка, умеющая только привести к отказу, честнее не рисоваться.
 */
export default function AnalogueDialog({ problem, onClose, onDone }) {
  const { t } = useTranslation()
  const [error, setError] = useState(null)

  const declare = async (other) => {
    try {
      await declareAnalogue(problem, other.id)
      onDone()
    } catch (trouble) {
      setError(trouble.message)
    }
  }

  return (
    <Modal title={t('bank.analogue.title')} onClose={onClose}>
      {error && <p className="error">{error}</p>}
      <p className="hint">{t('bank.analogue.hint')}</p>

      <ProblemPicker except={problem} pick={t('bank.analogue.pick')} onPick={declare} />
    </Modal>
  )
}
