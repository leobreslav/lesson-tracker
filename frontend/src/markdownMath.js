/**
 * `$$…$$` on one line means display maths.
 *
 * remark-math disagrees: its block construct wants the delimiters on lines of
 * their own, so a formula written the way Pandoc, Obsidian and every LaTeX
 * habit write it —
 *
 *     $$N = \sum a_i \pmod 3$$
 *
 * — comes out as *inline* maths, small and squeezed into the line. Teachers
 * write it that way, so the renderer meets them there instead of demanding
 * three lines for one formula.
 *
 * The rule is deliberately narrow: a paragraph whose whole content is one
 * maths expression is a displayed formula. A formula with any words around it
 * stays inline, which is what inline maths is for.
 */

const blank = (node) => node.type === 'text' && !node.value.trim()

/**
 * The shape rehype-katex looks for.
 *
 * remark-math does not hand its nodes to the HTML step as maths — it hands
 * them over as a `div`/`span` carrying `math math-display` or `math
 * math-inline`, and rehype-katex picks them up by that class. So promoting a
 * node means rewriting its `data`, not just its `type`: carrying the original
 * `data` across would keep the formula inline while calling it display, which
 * is exactly the bug this file was written to fix.
 */
const asDisplay = (value) => ({
  type: 'math',
  value,
  data: {
    hName: 'div',
    hProperties: { className: ['math', 'math-display'] },
    hChildren: [{ type: 'text', value }],
  },
})

/** The single maths child of a paragraph, if that is all the paragraph is. */
export function loneMath(paragraph) {
  if (paragraph.type !== 'paragraph') return null

  const meaningful = paragraph.children.filter((child) => !blank(child))
  const [only] = meaningful

  return meaningful.length === 1 && only.type === 'inlineMath' ? only : null
}

/** Rewrite in place; returns how many paragraphs were promoted. */
export function promote(node) {
  if (!node?.children) return 0

  let changed = 0
  node.children = node.children.map((child) => {
    const math = loneMath(child)
    if (math) {
      changed += 1
      return asDisplay(math.value)
    }
    changed += promote(child)
    return child
  })

  return changed
}

/** The remark plugin itself. */
export default function remarkDisplayLoneMath() {
  return (tree) => {
    promote(tree)
  }
}
