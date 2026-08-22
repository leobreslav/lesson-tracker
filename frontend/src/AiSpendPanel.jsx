import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fetchAiBudget, fetchAiSpend, saveAiBudget } from './api'
import { shortDate } from './dates'

/**
 * Расход на чтение сканов: потолок и журнал.
 *
 * Один блок на две роли, а не два экрана. Администратор видит траты всей школы
 * и правит потолок; учитель — свои строки и потолок на чтение. Вопрос у них
 * разный («не пора ли поднять» против «во что обошлась пачка»), но данные одни
 * и те же, и разойтись они не должны.
 *
 * Деньги показываются в долларах: в них выставляет счёт Anthropic, и переводить
 * их во что-то другое значит объяснять человеку курс, по которому мы сами не
 * платим.
 */
export default function AiSpendPanel() {
  const { t } = useTranslation()
  const [budget, setBudget] = useState(null)
  const [rows, setRows] = useState([])
  const [limit, setLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = async () => {
    try {
      const [money, log] = await Promise.all([fetchAiBudget(), fetchAiSpend()])
      setBudget(money)
      setLimit(String(money.limit_cents))
      setRows(log.rows)
    } catch (problem) {
      setError(problem.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const money = await saveAiBudget(Number(limit))
      setBudget({ ...budget, ...money })
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!budget) return null

  const dollars = (micros) => `$${(micros / 1_000_000).toFixed(2)}`

  return (
    <section className="panel" data-panel="ai-spend">
      <h3>{t('ai.title')}</h3>
      <p className="hint">{t('ai.hint')}</p>
      {error && <p className="error">{error}</p>}

      <p>
        {t('ai.spent', {
          spent: dollars(budget.spent_micros),
          limit: dollars(budget.limit_micros),
        })}
      </p>

      {budget.may_edit && (
        <div className="row">
          <label className="field">
            <span>{t('ai.limit')}</span>
            <input
              type="number"
              min="0"
              value={limit}
              disabled={busy}
              onChange={(event) => setLimit(event.target.value)}
            />
          </label>
          <button type="button" disabled={busy} onClick={save}>
            {t('common.save')}
          </button>
          <span className="hint">{t('ai.limitHint')}</span>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="hint">{t('ai.none')}</p>
      ) : (
        <ul className="ai-log">
          {rows.map((row) => (
            <li key={row.id}>
              <span className="hint">{shortDate(row.at)}</span>
              <span>{row.work_title || t('ai.noWork')}</span>
              {budget.may_edit && <span className="hint">{row.who}</span>}
              <b>{dollars(row.cost_micros)}</b>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
