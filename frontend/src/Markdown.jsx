import Markdown, { defaultUrlTransform } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import LessonImage, { imageFile } from './LessonImage'
import remarkDisplayLoneMath from './markdownMath'
import remarkImageAttributes, { remarkBlockOffsets } from './markdownImages'
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
 *
 * Pictures go through `LessonImage`, always and everywhere: the bucket is
 * private, so `![](file:12)` is not an address a browser can follow and has
 * to be traded for a signed one first.
 *
 * `blocks` labels every top-level block with where it starts in the source.
 * Reading does not need that; the editor does, and it is the only way back
 * from a paragraph on the screen to the characters it was made of.
 */

/**
 * `file:12` has to reach `LessonImage`, and by default it does not.
 *
 * react-markdown scrubs every address whose protocol is not `http`, `https`,
 * `mailto` or `tel` — a guard against `javascript:` in text somebody else
 * wrote, and a good one. Ours is not an address at all, though: it names a
 * file, `LessonImage` trades it for a signed link, and nothing ever follows
 * it. Left to the default it came out empty, and the picture vanished in
 * silence — which is exactly how this was found.
 *
 * Everything that is not ours goes on being scrubbed.
 */
const address = (value, key, node) =>
  imageFile(value) === null ? defaultUrlTransform(value, key, node) : value

const REMARK = [remarkGfm, remarkMath, remarkImageAttributes, remarkDisplayLoneMath]
const REMARK_WITH_BLOCKS = [...REMARK, remarkBlockOffsets]
const REHYPE = [[rehypeKatex, { throwOnError: false, strict: 'ignore' }]]

const COMPONENTS = { img: LessonImage }

export default function Rendered({
  text,
  className = 'markdown',
  blocks = false,
  components,
}) {
  if (!text?.trim()) return null

  return (
    <div className={className}>
      <Markdown
        remarkPlugins={blocks ? REMARK_WITH_BLOCKS : REMARK}
        rehypePlugins={REHYPE}
        urlTransform={address}
        components={components ? { ...COMPONENTS, ...components } : COMPONENTS}
      >
        {text}
      </Markdown>
    </div>
  )
}
