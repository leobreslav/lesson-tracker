import Markdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkDisplayLoneMath from './markdownMath'
import 'katex/dist/katex.min.css'

/**
 * Lesson content, rendered.
 *
 * The stored text is Markdown and stays Markdown — this is the only place
 * that turns it into anything else, and it does so on the way to the screen,
 * never on the way to the database. That is what keeps a lesson exportable
 * into LaTeX years later.
 *
 * KaTeX rather than MathJax: it renders synchronously and an order of
 * magnitude faster, and the subset it covers is well past what school maths
 * needs. A formula it cannot parse is shown in red in place, not thrown —
 * a typo in one line must not blank the lesson.
 */

const REMARK = [remarkGfm, remarkMath, remarkDisplayLoneMath]
const REHYPE = [[rehypeKatex, { throwOnError: false, strict: 'ignore' }]]

export default function Rendered({ text, className = 'markdown' }) {
  if (!text?.trim()) return null

  return (
    <div className={className}>
      <Markdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
        {text}
      </Markdown>
    </div>
  )
}
