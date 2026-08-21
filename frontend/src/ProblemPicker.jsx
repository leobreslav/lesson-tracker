import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Markdown from './Markdown'
import { searchProblems } from './api'

/**
 * Найти условие в банке и выбрать его.
 *
 * Один список на все места, где спрашивают «какую задачу»: отметить аналог,
 * накатить условие на ячейку работы. Заводить ради каждого свой поиск значило
 * бы завести и второе место, где живут правила видимости.
 *
 * Показывается **всё своё**, включая набранное на бегу в других работах: самый
 * частый вопрос к банку — «я это уже спрашивал», и черновые он обязан находить
 * тоже. Где условие лежит, сказано в строке.
 */
export default function ProblemPicker({ except, pick, onPick }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [found, setFound] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => {
      searchProblems({ text })
        .then(
          (answer) =>
            alive &&
            setFound(answer.problems.filter((one) => one.id !== except)),
        )
        .catch((problem) => alive && setError(problem.message))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [text, except])

  return (
    <>
      {error && <p className="error">{error}</p>}

      <label className="field">
        <span>{t('bank.search.text')}</span>
        <input value={text} onChange={(event) => setText(event.target.value)} autoFocus />
      </label>

      <ul className="problem-list">
        {found.map((problem) => (
          <li key={problem.id}>
            <span className="label">#{problem.id}</span>
            <span className="text">
              <Markdown text={problem.text} />
              <span className="hint">
                {problem.where ? problem.where.title : t('bank.search.nowhere')}
              </span>
            </span>
            <button
              type="button"
              className="secondary compact"
              onClick={() => onPick(problem)}
            >
              {pick}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}
