import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchPlanDiff } from './api'
import MathText from './MathText'
import { longDate } from './dates'

const COUNTS = ['added', 'removed', 'changed', 'moved']

/**
 * Что изменилось с утверждения — отдельным видом, а не подкраской таблицы.
 *
 * Страница плана целиком уходит: панель управления, сводка, сама таблица со
 * всеми её ручками и формами. Причина не в аккуратности, а в том, что
 * сравнение показывает **удалённые** строки — призраками на их прежних
 * местах, — а призрак в живой таблице нельзя ни утащить, ни нажать, и он
 * спорит с правилами очереди. Дат у призраков тоже нет: у удалённой строки
 * не осталось часа, и пустить её в сшивку значит сдвинуть все даты ниже.
 *
 * Сопоставление точное, по `node_id`: переименование видно переименованием,
 * а не парой «удалили и добавили». Считает его сервер — `plans/diff.py`, —
 * и по той же ленте, из которой собраны числа наверху.
 */
/**
 * Сами строки сравнения — без рамки и без запроса.
 *
 * Тот же список видят обе стороны: автор на месте своей таблицы, методист
 * на месте присланного плана. Разные разметки для одного ответа разошлись
 * бы в первую же правку, и спор о том, что показано, начался бы заново.
 */
export function DiffBody({ data }) {
  const { t } = useTranslation()
  const changed = data.rows.filter((row) => row.state !== 'same')

  if (changed.length === 0) return <p className="hint">{t('plan.diff.empty')}</p>

  return (
    <>
      <p className="hint diff-counts">
        {COUNTS.filter((name) => data.counts[name]).map((name) => (
          <span key={name} className={`diff-count ${name}`}>
            <b>{data.counts[name]}</b> {t(`plan.diff.${name}`)}
          </span>
        ))}
      </p>

      <ul className="diff-rows">
        {data.rows.map((row, index) => (
          <li
            // призрак и живая строка могут нести один id только в
            // невозможном плане, но ключ всё равно берём с позицией:
            // порядок здесь и есть содержание
            key={`${row.id}-${index}`}
            className={`diff-row ${row.state}${row.is_section ? ' section' : ''}`}
          >
            <span className="diff-mark" aria-hidden="true">
              {row.state === 'added'
                ? '+'
                : row.state === 'removed'
                  ? '−'
                  : row.state === 'moved'
                    ? '↕'
                    : row.state === 'changed'
                      ? '±'
                      : ''}
            </span>
            <span className="diff-title">
              <MathText text={row.title} />
            </span>
            {row.was_title && (
              <span className="hint">
                {t('plan.diff.was', { title: row.was_title })}
              </span>
            )}
            {row.content_changed && (
              <span className="hint">{t('plan.diff.content')}</span>
            )}
          </li>
        ))}
      </ul>

      <p className="hint">{t('plan.diff.legend')}</p>
    </>
  )
}


export default function PlanDiff({ classId, onClose }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let current = true
    setData(null)
    setError(null)

    fetchPlanDiff(classId)
      .then((result) => current && setData(result))
      .catch((err) => current && setError(err.message))

    return () => {
      current = false
    }
  }, [classId])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p>{t('common.loading')}</p>
  if (!data.baseline) return <p className="hint">{t('plan.diff.none')}</p>

  return (
    <section className="panel plan-diff">
      <div className="panel-head spread">
        <h2>{t('plan.diff.title')}</h2>
        <button type="button" className="secondary" onClick={onClose}>
          {t('plan.diff.back')}
        </button>
      </div>

      <p className="hint">
        {t('plan.diff.since', {
          date: longDate(data.baseline.approved_at.slice(0, 10)),
        })}
      </p>

      <DiffBody data={data} />
    </section>
  )
}
