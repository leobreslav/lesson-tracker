import { useTranslation } from 'react-i18next'

import Markdown from './Markdown'

/**
 * Условие ячейки на экране: шапка сюжета, сам вопрос и пометка «это пункт».
 *
 * Одно место на все три экрана — банк, работа, ученик, — потому что правил
 * тут три и они неочевидные, а разойтись отрисовкам ничего не стоит:
 *
 * 1. **пункт без сюжета не показывают.** «Найдите радиус» без треугольника
 *    бессмысленно, поэтому шапка идёт вместе с вопросом;
 * 2. **соседние пункты не показывают никогда.** В работе спрашивают то, что
 *    спросили, и чужой вопрос рядом читается как «а это тоже решать?»;
 * 3. **выключенная шапка выключает и пометку — но только ученику.** Иначе
 *    скрытие бессмысленно: он одним нажатием увидел бы спрятанное. Решает это
 *    сервер (`statements.shown`), сюда приезжает уже готовый ответ.
 *
 * `onWhole` — «показать целиком»; даётся там, где есть куда вести (у учителя
 * это страница условия в банке). Нет обработчика — нет и ссылки.
 */
export default function Statement({ shown, onWhole }) {
  const { t } = useTranslation()

  if (!shown) return null

  return (
    <div className="statement">
      {shown.stem && (
        <div className="statement-stem">
          <Markdown text={shown.stem.text} />
        </div>
      )}

      <Markdown text={shown.text} />

      {shown.is_part && (
        <p className="hint">
          {t('works.task.isPart')}
          {onWhole && (
            <button type="button" className="link" onClick={onWhole}>
              {t('works.task.whole')}
            </button>
          )}
        </p>
      )}
    </div>
  )
}
