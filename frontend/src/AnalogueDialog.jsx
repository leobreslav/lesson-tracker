import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Markdown from './Markdown'
import Modal from './Modal'
import { declareAnalogue, searchProblems } from './api'

/**
 * «Это аналог вот той» — то есть та же задача с другими числами.
 *
 * Ищется вторая задача тем же поиском, что и везде: заводить ради одного окна
 * второй способ найти условие значит завести и второе место, где живут правила
 * видимости.
 *
 * Свою же задачу в списке не показываем: «аналог самого себя» сервер отклонит,
 * а строка, умеющая только привести к отказу, честнее не рисоваться.
 */
export default function AnalogueDialog({ problem, onClose, onDone }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [found, setFound] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => {
      searchProblems({ text })
        .then((answer) => alive && setFound(answer.problems.filter((one) => one.id !== problem)))
        .catch((trouble) => alive && setError(trouble.message))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [text, problem])

  const declare = async (other) => {
    try {
      await declareAnalogue(problem, other)
      onDone()
    } catch (trouble) {
      setError(trouble.message)
    }
  }

  return (
    <Modal title={t('bank.analogue.title')} onClose={onClose}>
      {error && <p className="error">{error}</p>}
      <p className="hint">{t('bank.analogue.hint')}</p>

      <label className="field">
        <span>{t('bank.search.text')}</span>
        <input value={text} onChange={(event) => setText(event.target.value)} autoFocus />
      </label>

      <ul className="problem-list">
        {found.map((one) => (
          <li key={one.id}>
            <span className="label">#{one.id}</span>
            <span className="text">
              <Markdown text={one.text} />
            </span>
            <button type="button" className="secondary compact" onClick={() => declare(one.id)}>
              {t('bank.analogue.pick')}
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
