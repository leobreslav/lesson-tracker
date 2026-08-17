import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchPlanDiff } from './api'
import MathText from './MathText'
import { dateTime, longDate } from './dates'

const COUNTS = ['added', 'removed', 'changed', 'moved']

/**
 * Сами строки сравнения — без рамки и без запроса.
 *
 * Тот же список видят обе стороны: автор на месте своей таблицы, методист
 * на месте присланного плана. Разные разметки для одного ответа разошлись
 * бы в первую же правку, и спор о том, что показано, начался бы заново.
 *
 * Выбор версии стоит **здесь же и всегда** — в том числе когда с последним
 * утверждением не изменилось ничего. Иначе «с тех пор всё то же» было бы
 * тупиком: спросить «а с начала года?» стало бы негде.
 */
export function DiffBody({ data, onVersion }) {
  const { t } = useTranslation()
  const changed = data.rows.filter((row) => row.state !== 'same')
  const versions = data.versions ?? []

  /**
   * Подпись версии — дата, а при совпадении дат ещё и время.
   *
   * План правят и подписывают дважды за день: поправили замечание, отдали
   * снова. Две одинаковые строки в списке — это выбор вслепую, а время в
   * каждой строке ради такого случая было бы шумом на весь год.
   */
  const dates = versions.map((item) => item.approved_at.slice(0, 10))
  const label = (item) => {
    const day = item.approved_at.slice(0, 10)
    return dates.filter((other) => other === day).length > 1
      ? dateTime(item.approved_at)
      : longDate(day)
  }

  return (
    <>
      {versions.length > 1 ? (
        <label className="row diff-version">
          <span className="hint">{t('plan.diff.version')}</span>
          <select
            value={data.baseline.id}
            onChange={(event) => onVersion(event.target.value)}
          >
            {versions.map((item) => (
              <option key={item.id} value={item.id}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="hint">
          {t('plan.diff.since', {
            date: longDate(data.baseline.approved_at.slice(0, 10)),
          })}
        </p>
      )}

      {changed.length === 0 ? (
        <p className="hint">{t('plan.diff.empty')}</p>
      ) : (
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
      )}
    </>
  )
}

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
 *
 * Переключает вид тумблер в шапке страницы, поэтому своей кнопки «назад» у
 * этого экрана нет: один выбор — один орган управления.
 */
export default function PlanDiff({ classId }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  // выбранная версия эталона; null — последнее утверждение, то есть ответ
  // на «что я поменял с тех пор, как подписали»
  const [chosen, setChosen] = useState(null)

  useEffect(() => {
    setChosen(null)
    setData(null)
  }, [classId])

  useEffect(() => {
    let current = true
    setError(null)
    // прежний ответ не гасим: при смене версии селект должен остаться на
    // месте, а не мигать «загрузкой» под рукой

    fetchPlanDiff(classId, chosen)
      .then((result) => current && setData(result))
      .catch((err) => current && setError(err.message))

    return () => {
      current = false
    }
  }, [classId, chosen])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p>{t('common.loading')}</p>
  if (!data.baseline) return <p className="hint">{t('plan.diff.none')}</p>

  return (
    <section className="panel plan-diff">
      <h2>{t('plan.diff.title')}</h2>
      <DiffBody data={data} onVersion={setChosen} />
    </section>
  )
}
