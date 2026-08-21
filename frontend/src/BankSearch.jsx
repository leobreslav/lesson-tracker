import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Basket from './Basket'
import ExpressionEditor from './ExpressionEditor'
import MathText from './MathText'
import Pick from './Pick'
import Switch from './Switch'
import SubjectPicker, { chosenSubject } from './SubjectPicker'
import { prune } from './expressionTree'
import { taken } from './basket'
import {
  fetchTags,
  fetchTopics,
  saveTopic,
  searchByExpression,
  searchProblems,
} from './api'

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
  const [picked, setPicked] = useState(taken())
  // '' — всё своё, 'yes' — разложенное по книгам, 'no' — только из работ
  const [shelved, setShelved] = useState('')
  const [subject, setSubject] = useState(chosenSubject())
  // Второй вход в тот же набор: грани отвечают только на «и», выражение — на
  // «или» и на отрицание. Вид один за раз: два списка результатов рядом
  // означали бы два ответа на вопрос «что нашлось».
  const [byTree, setByTree] = useState(false)
  const [tree, setTree] = useState({ all: [] })
  // Словарь целиком — им наполняются селекты в выражении.
  const [vocabulary, setVocabulary] = useState([])
  const [saved, setSaved] = useState([])
  const [naming, setNaming] = useState(null)

  useEffect(() => {
    fetchTags()
      .then((answer) => setVocabulary(answer.tags))
      .catch(() => setVocabulary([]))
    // Сохранённые поиски и темы — одно и то же: названное условие. Здесь
    // показываются те, что без родителя: их условие ни с чем не складывается,
    // и подставить его в поиск можно как есть.
    fetchTopics()
      .then((answer) => setSaved(answer.topics.filter((one) => !one.parent)))
      .catch(() => setSaved([]))
  }, [])

  // грани, выбранные с этой стороны: у тега на условии стороны нет вовсе
  const facetsOf = (side) =>
    chosen.filter((one) => one.side === side).map((one) => one.tag)
  const tags = facetsOf('')
  const uses = facetsOf('uses')
  const avoids = facetsOf('avoids')
  const key = chosen.map((one) => `${one.tag}${one.side}`).join(',')

  useEffect(() => {
    let alive = true
    // Слово набирают по букве, и запрос на каждую — это запрос на каждую.
    const timer = setTimeout(() => {
      // Недописанное выражение — это ещё не запрос: пустое дерево значит
      // «без условий», и отвечать на него должен обычный поиск, а не отказ.
      const trimmed = byTree ? prune(tree) : null
      const asked =
        byTree && trimmed
          ? searchByExpression(trimmed)
          : searchProblems(
              byTree ? { subject } : { text, tags, uses, avoids, shelved, subject },
            )
      asked
        .then((answer) => {
          if (!alive) return
          setFound(answer)
          setError(null)
        })
        .catch((problem) => alive && setError(problem.message))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, key, byTree, shelved, subject, JSON.stringify(tree)])

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

      <Basket picked={picked} onChange={setPicked} />

      <section className="panel">
        <div className="row">
          <SubjectPicker value={subject} onChange={setSubject} />
          <Switch
            value={byTree ? 'tree' : 'facets'}
            options={[
              { value: 'facets', label: t('bank.expression.byFacets') },
              { value: 'tree', label: t('bank.expression.byExpression') },
            ]}
            onChange={(value) => setByTree(value === 'tree')}
          />
          {saved.length > 0 && (
            <label className="field">
              <span>{t('bank.saved.title')}</span>
              <select
                value=""
                onChange={(event) => {
                  const one = saved.find((row) => String(row.id) === event.target.value)
                  if (!one) return
                  setTree(one.expression)
                  setByTree(true)
                }}
              >
                <option value="">—</option>
                {saved.map((one) => (
                  <option key={one.id} value={one.id}>
                    {one.title}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        {byTree ? (
          <>
            <ExpressionEditor node={tree} tags={vocabulary} onChange={(next) => setTree(next || { all: [] })} />
            <div className="row">
              {naming === null ? (
                <button type="button" className="secondary compact" onClick={() => setNaming('')}>
                  {t('bank.saved.save')}
                </button>
              ) : (
                <>
                  <label className="field">
                    <span>{t('bank.saved.name')}</span>
                    <input value={naming} onChange={(event) => setNaming(event.target.value)} />
                  </label>
                  <button
                    type="button"
                    disabled={!naming.trim()}
                    onClick={async () => {
                      try {
                        await saveTopic({
                          title: naming,
                          expression: prune(tree) || {},
                        })
                        setNaming(null)
                        setSaved(
                          (await fetchTopics()).topics.filter((one) => !one.parent),
                        )
                      } catch (problem) {
                        setError(problem.message)
                      }
                    }}
                  >
                    {t('common.save')}
                  </button>
                  <button type="button" className="link" onClick={() => setNaming(null)}>
                    {t('common.cancel')}
                  </button>
                </>
              )}
            </div>
          </>
        ) : (
          <div className="row">
            <label className="field">
              <span>{t('bank.search.text')}</span>
              <input value={text} onChange={(event) => setText(event.target.value)} />
            </label>
            <label className="field">
              <span>{t('bank.search.where')}</span>
              <select value={shelved} onChange={(event) => setShelved(event.target.value)}>
                <option value="">{t('bank.search.anywhere')}</option>
                <option value="yes">{t('bank.search.inBooks')}</option>
                <option value="no">{t('bank.search.onlyInWorks')}</option>
              </select>
            </label>
          </div>
        )}

        {!byTree && chosen.length > 0 && (
          <p className="chosen-facets">
            {chosen.map((facet) => (
              <button
                key={`${facet.tag}-${facet.side}`}
                type="button"
                className={`tag ${facet.side === 'avoids' ? 'avoids' : ''}`}
                onClick={() => drop(facet)}
              >
                {label(t, facet)} ✕
              </button>
            ))}
          </p>
        )}
      </section>

      <div className="bank-columns">
        <section className="panel">
          <h2>{byTree ? t('bank.expression.what') : t('bank.search.facets')}</h2>
          {found && found.facets.length === 0 && (
            <p className="hint">{t('bank.search.noFacets')}</p>
          )}
          <ul className="facet-list">
            {(found ? found.facets : []).map((facet) => (
              <li key={`${facet.tag}-${facet.side}`}>
                <button
                  type="button"
                  className="link"
                  disabled={byTree}
                  onClick={() => take(facet)}
                >
                  {label(t, facet)}
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
                <Pick id={problem.id} picked={picked} onChange={setPicked} />
                <span className="text">
                  <Link to={`/bank/problem/${problem.id}`}>
                    <MathText text={problem.text} />
                  </Link>
                </span>
                <span className="hint">
                  {/* семья стоит одной строкой: аналогов бывают сотни, и
                      каждый из них — та же задача с другими числами */}
                  {problem.analogues > 0 && (
                    <>{t('bank.search.analogues', { count: problem.analogues })} · </>
                  )}
                  {problem.where ? problem.where.title : t('bank.search.nowhere')}
                </span>
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

/**
 * Подпись грани.
 *
 * Сторону приходится называть словом: «алгебра» на условии и «алгебра» в
 * решении — разные грани с разными числами, а в списке они выглядели
 * одинаково. Две одинаковые строки подряд читаются как дубль, и какая из них
 * какая, узнать было нельзя ничем.
 */
function label(t, facet) {
  if (facet.side === 'uses') return `${t('bank.inSolution')}: ${facet.name}`
  if (facet.side === 'avoids') return `${t('bank.inSolution')} ${t('bank.without')}: ${facet.name}`
  return facet.name
}
