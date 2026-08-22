import { useTranslation } from 'react-i18next'

import Switch from './Switch'

/**
 * Правка логического выражения из граней.
 *
 * Фасетный поиск отвечает только на «и», а спрашивают и «или»: «уравнение или
 * неравенство, но без производной». Выразить это чипами нельзя, поэтому рядом
 * с ними стоит дерево.
 *
 * Дерево рисуется отступом и **ничего не прячет**: свёрнутая группа означала
 * бы, что человек ищет по условию, которого не видит, — а разбираются с
 * выражением ровно тогда, когда нашлось не то.
 *
 * Форма узла та же, что понимает сервер (`bank/expressions.py`), и это
 * намеренно: переводить одну форму в другую значит завести второе место, где
 * живут правила, и однажды разойтись с ним.
 */
export default function ExpressionEditor({ node, tags, onChange }) {
  const { t } = useTranslation()
  return (
    <Group node={node} tags={tags} onChange={onChange} t={t} top />
  )
}

function Group({ node, tags, onChange, t, top }) {
  const every = 'all' in node
  const parts = node.all || node.any || []

  const replace = (index, part) => {
    const next = [...parts]
    if (part === null) next.splice(index, 1)
    else next[index] = part
    onChange(every ? { all: next } : { any: next })
  }

  return (
    <div className={`expression-group ${top ? 'top' : ''}`}>
      <div className="row">
        <Switch
          value={every ? 'all' : 'any'}
          options={[
            { value: 'all', label: t('bank.expression.all') },
            { value: 'any', label: t('bank.expression.any') },
          ]}
          onChange={(value) =>
            onChange(value === 'all' ? { all: parts } : { any: parts })
          }
        />
        <button type="button" className="secondary compact" onClick={() => replace(parts.length, { tag: tags[0]?.id })}>
          {t('bank.expression.addLeaf')}
        </button>
        <button
          type="button"
          className="secondary compact"
          onClick={() => replace(parts.length, { all: [{ tag: tags[0]?.id }] })}
        >
          {t('bank.expression.addGroup')}
        </button>
        {!top && (
          <button type="button" className="link" onClick={() => onChange(null)}>
            ✕
          </button>
        )}
      </div>

      <ul className="expression-parts">
        {parts.map((part, index) => (
          <li key={index}>
            {isGroup(part) ? (
              <Group
                node={part}
                tags={tags}
                t={t}
                onChange={(next) => replace(index, next)}
              />
            ) : (
              <Leaf
                node={part}
                tags={tags}
                t={t}
                onChange={(next) => replace(index, next)}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Лист: тег со стороной, слово — или то же самое с отрицанием.
 *
 * Отрицание тут галочка, а не отдельный вид узла на экране: «не алгебра» это
 * та же грань, просто наоборот, и заводить её вторым способом значит
 * заставлять человека удалять строку, чтобы поменять знак.
 */
function Leaf({ node, tags, t, onChange }) {
  const negated = 'not' in node
  const inner = negated ? node.not : node
  const wrap = (next) => onChange(negated ? { not: next } : next)

  return (
    <div className="row expression-leaf">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={negated}
          onChange={(event) => onChange(event.target.checked ? { not: inner } : inner)}
        />
        <span>{t('bank.expression.not')}</span>
      </label>

      {'text' in inner ? (
        <input
          value={inner.text || ''}
          aria-label={t('bank.search.text')}
          onChange={(event) => wrap({ text: event.target.value })}
        />
      ) : (
        <>
          <select
            value={inner.tag || ''}
            aria-label={t('bank.expression.tag')}
            onChange={(event) => wrap({ ...inner, tag: Number(event.target.value) })}
          >
            {tags.map((tag) => (
              <option key={tag.id} value={tag.id}>
                {' '.repeat(tag.depth * 2)}
                {tag.name}
              </option>
            ))}
          </select>
          <select
            value={inner.side || ''}
            aria-label={t('bank.expression.side')}
            onChange={(event) =>
              wrap({ tag: inner.tag, ...(event.target.value ? { side: event.target.value } : {}) })
            }
          >
            <option value="">{t('bank.expression.onProblem')}</option>
            <option value="uses">{t('bank.expression.uses')}</option>
            <option value="avoids">{t('bank.expression.avoids')}</option>
          </select>
        </>
      )}

      <button
        type="button"
        className="link"
        onClick={() => wrap('text' in inner ? { tag: tags[0]?.id } : { text: '' })}
      >
        {'text' in inner ? t('bank.expression.byTag') : t('bank.expression.byWord')}
      </button>
      <button type="button" className="link" onClick={() => onChange(null)}>
        ✕
      </button>
    </div>
  )
}

const isGroup = (node) => 'all' in node || 'any' in node
