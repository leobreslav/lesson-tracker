import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { linkTag, unlinkTag } from './api'

/**
 * Теги на условии или на решении: показать, повесить, снять.
 *
 * Одна полоска на оба случая, потому что разница между ними — в списке видов и
 * в наличии знака, а не в том, как это выглядит и что с этим делают.
 *
 * У решения теги **со знаком**: «использует» и «намеренно обходится». Второе —
 * утверждение человека, а не отсутствие первого: именно на нём держится поиск
 * «разбор без производной», ради которого вся разметка и заведена. Знак
 * спрашивается сразу, вторым селектом, — потому что «повесил, а потом поменял
 * знак» это два действия там, где человек делает одно.
 *
 * Отрицать можно только метод и теорему: «без окружности» не значит ничего.
 * Сервер это отклоняет, поэтому и селект знака показывается не всегда — кнопка,
 * умеющая только привести к отказу, честнее не рисоваться.
 */
export default function TagStrip({ tags, vocabulary, kinds, mayEdit, target, onChange }) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const [chosen, setChosen] = useState('')
  const [side, setSide] = useState('uses')
  const [error, setError] = useState(null)

  const allowed = vocabulary.filter((tag) => kinds.includes(tag.kind))
  const negatable = allowed.find((tag) => String(tag.id) === chosen)
  const mayNegate = target.solution && ['theorem', 'method'].includes(negatable?.kind)

  const run = async (what) => {
    try {
      await what
      setError(null)
      onChange()
    } catch (problem) {
      setError(problem.message)
    }
  }

  return (
    <div className="tag-strip">
      {tags.map((tag) => (
        <span key={tag.id} className={`tag ${tag.side === 'avoids' ? 'avoids' : ''}`}>
          {tag.side === 'avoids' && `${t('bank.without')} `}
          {tag.name}
          {mayEdit && (
            <button
              type="button"
              className="link"
              aria-label={t('bank.tags.remove', { name: tag.name })}
              onClick={() => run(unlinkTag({ ...target, tag: tag.id }))}
            >
              ✕
            </button>
          )}
        </span>
      ))}

      {mayEdit &&
        (adding ? (
          <span className="row">
            <select
              autoFocus
              aria-label={t('bank.expression.tag')}
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
            >
              <option value="">—</option>
              {allowed.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
            </select>
            {mayNegate && (
              <select
                aria-label={t('bank.tags.side')}
                value={side}
                onChange={(event) => setSide(event.target.value)}
              >
                <option value="uses">{t('bank.expression.uses')}</option>
                <option value="avoids">{t('bank.expression.avoids')}</option>
              </select>
            )}
            <button
              type="button"
              className="secondary compact"
              disabled={!chosen}
              onClick={async () => {
                await run(linkTag({ ...target, tag: Number(chosen), side }))
                setAdding(false)
                setChosen('')
              }}
            >
              {t('bank.tags.add')}
            </button>
            <button type="button" className="link" onClick={() => setAdding(false)}>
              {t('common.cancel')}
            </button>
          </span>
        ) : (
          <button type="button" className="link" onClick={() => setAdding(true)}>
            {t('bank.tags.open')}
          </button>
        ))}

      {error && <span className="error">{error}</span>}
    </div>
  )
}
