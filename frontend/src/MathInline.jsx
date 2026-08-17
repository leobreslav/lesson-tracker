import katex from 'katex'
import { splitMath } from './mathText'
import 'katex/dist/katex.min.css'

/**
 * Название с формулами — отдельным куском бандла.
 *
 * KaTeX с таблицей стилей весит столько же, сколько половина приложения,
 * и учителю, у которого в названиях нет ни одного доллара, платить за него
 * незачем. Поэтому файл грузится лениво и **только** когда формула в
 * строке действительно есть; решает это `MathText`.
 *
 * Зовём KaTeX напрямую, без react-markdown: в названии не бывает ни
 * списков, ни заголовков, а разбирать одну строку ради `$…$` целым
 * конвейером ремарков — платить второй раз за то же самое.
 *
 * Формула, которую KaTeX не понял, показывается красным на своём месте, а
 * не роняет строку: `throwOnError: false` — то же правило, что в
 * содержании урока.
 */
export default function MathInline({ text }) {
  return (
    <>
      {splitMath(text).map((part, index) =>
        part.math ? (
          <span
            key={index}
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(part.text, {
                throwOnError: false,
                strict: 'ignore',
              }),
            }}
          />
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </>
  )
}
