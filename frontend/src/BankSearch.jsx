import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import MathText from './MathText'
import { searchProblems } from './api'

/**
 * Поиск задачи по граням и по тексту.
 *
 * Устроен как фасетный поиск в магазине, и по той же причине: словарь тегов
 * велик, к текущему набору подходит десяток из них, а какой именно — заранее
 * не угадать. Поэтому рядом с каждой невыбранной гранью стоит число: сколько
 * задач останется, если её добавить. Список без чисел означал бы выбор
 * вслепую, а грань, оставляющая ноль, читалась бы как поломка поиска.
 *
 * Выбранные грани стоят наверху строкой чипов с крестиками — снять надо там
 * же, где выбрал, а не искать в общем списке.
 */
export default function BankSearch() {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  // Грань хранится целиком, вместе с именем: снятая из общего списка она
  // исчезает, и восстановить её подпись потом неоткуда.
  const [chosen, setChosen] = useState([])
  const [found, setFound] = useState(null)
  const [error, setError] = useState(null)

  const picked = (side) =>
    chosen.filter((one) => one.side === side).map((one) => one.tag)
  const tags = picked('')
  const uses = picked('uses')
  const avoids = picked('avoids')
  const key = chosen.map((one) => `${one.tag}${one.side}`).join(',')

  useEffect(() => {
    let alive = true
    // Слово набирают по букве, и запрос на каждую — это запрос на каждую.
    const timer = setTimeout(() => {
      searchProblems({ text, tags, uses, avoids })
        .then((answer) => alive && setFound(answer))
        .catch((problem) => alive && setError(problem.message))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, key])

  const drop = (facet) =>
    setChosen(chosen.filter((one) => !(one.tag === facet.tag && one.side === facet.side)))
  const take = (facet) =>
    setChosen([...chosen, { tag: facet.tag, side: facet.side, name: facet.name }])

  return (
    <main className="page wide">
      <header className="page-header spread">
        <h1>{t('bank.search.title')}</h1>
        <Link to="/bank">{t('bank.title')}</Link>
      </header>

      {error && <p className="error">{error}</p>}

      <section className="panel">
        <div className="row">
          <label className="field">
            <span>{t('bank.search.text')}</span>
            <input value={text} onChange={(event) => setText(event.target.value)} />
          </label>
        </div>

        {chosen.length > 0 && (
          <p className="chosen-facets">
            {chosen.map((facet) => (
              <button
                key={`${facet.tag}-${facet.side}`}
                type="button"
                className={`tag ${facet.side === 'avoids' ? 'avoids' : ''}`}
                onClick={() => drop(facet)}
              >
                {facet.side === 'avoids' ? `${t('bank.without')} ` : ''}
                {facet.name} ✕
              </button>
            ))}
          </p>
        )}
      </section>

      <div className="bank-columns">
        <section className="panel">
          <h2>{t('bank.search.facets')}</h2>
          {found && found.facets.length === 0 && (
            <p className="hint">{t('bank.search.noFacets')}</p>
          )}
          <ul className="facet-list">
            {(found ? found.facets : []).map((facet) => (
              <li key={`${facet.tag}-${facet.side}`}>
                <button type="button" className="link" onClick={() => take(facet)}>
                  {facet.side === 'avoids' ? `${t('bank.without')} ` : ''}
                  {facet.name}
                </button>
                <span className="count">{facet.count}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel">
          <h2>
            {found
              ? t('bank.search.found', { count: found.total })
              : t('common.loading')}
          </h2>
          <ul className="problem-list">
            {(found ? found.problems : []).map((problem) => (
              <li key={problem.id}>
                <span className="label" />
                <span className="text">
                  <Link to={`/bank/problem/${problem.id}`}>
                    <MathText text={problem.text} />
                  </Link>
                </span>
                <span className="hint">{t(`bank.levels.${problem.level}`)}</span>
              </li>
            ))}
          </ul>
          {found && found.total > found.shown && (
            <p className="hint">{t('bank.search.more', { count: found.total - found.shown })}</p>
          )}
        </section>
      </div>
    </main>
  )
}
