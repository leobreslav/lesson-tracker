/**
 * Two small bends in the Markdown pipeline, both about pictures.
 *
 * The first reads the attribute block Pandoc writes after an image —
 * `![](file:12){width=320 .right}` — which remark parses as an image
 * followed by the literal text `{width=320 .right}`. Left alone it would be
 * printed on the page, in braces, next to the picture it describes. So the
 * braces are eaten and turned into properties of the image itself.
 *
 * The second hands every top-level block the offset it starts at in the
 * source. Nothing on the reading side needs that; the editing side needs it
 * badly, because dragging a picture between two paragraphs on the screen has
 * to end up as an edit to a string of Markdown, and there is no other way
 * back from a rendered element to the characters it came from.
 *
 * Both write into `data.hProperties`, which is the door mdast leaves open
 * for exactly this: it is what remark-math uses to hand its formulas over to
 * rehype-katex, and going through `type` instead is the mistake documented
 * at length in `markdownMath.js`.
 */

import { parseAttrs } from './imageMarkdown.js'

const ATTRS = /^\{([^}]*)\}/

const propertiesOf = (node) => {
  const data = node.data ?? (node.data = {})
  return data.hProperties ?? (data.hProperties = {})
}

/**
 * One image, described.
 *
 * The class rides along even when nothing was said, so that the plain case
 * and the placed case are styled by one rule rather than two.
 */
export function describe(image, attrs = {}) {
  const { width = null, placement = 'block' } = attrs
  const properties = propertiesOf(image)

  properties.className = ['md-image', `md-image-${placement}`]
  if (width) properties.width = width

  const offset = image.position?.start?.offset
  // where in the source this picture is written: the editor's way back
  if (offset !== undefined) properties['data-offset'] = offset

  return image
}

/**
 * Eat the attribute block standing right after an image, if there is one.
 *
 * Returns how many images the parent had described this way — a number
 * rather than nothing, so the tests can say «this shape, and no other».
 */
export function absorb(parent) {
  const children = parent?.children
  if (!children) return 0

  let taken = 0

  for (let index = 0; index < children.length; index += 1) {
    const node = children[index]
    if (node.type !== 'image') continue

    const next = children[index + 1]
    const match = next?.type === 'text' ? ATTRS.exec(next.value) : null

    describe(node, match ? parseAttrs(match[1]) : {})
    if (!match) continue

    taken += 1
    next.value = next.value.slice(match[0].length)
    // a text node that was nothing but the braces has nothing left to say
    if (!next.value) children.splice(index + 1, 1)
  }

  return taken
}

const walk = (node, seen = 0) => {
  if (!node?.children) return seen
  const here = seen + absorb(node)
  return node.children.reduce((total, child) => walk(child, total), here)
}

/** The plugin itself: sizes and placements, everywhere in the tree. */
export default function remarkImageAttributes() {
  return (tree) => {
    walk(tree)
  }
}

/**
 * Top-level blocks, each labelled with where it starts in the source.
 *
 * Runs **after** the maths plugin on purpose: that one replaces a paragraph
 * holding a lone formula with a node of its own, and a plugin running before
 * it would label a node that no longer exists by the time it reaches the page.
 */
export function remarkBlockOffsets() {
  return (tree) => {
    for (const node of tree.children ?? []) {
      const offset = node.position?.start?.offset
      if (offset === undefined) continue

      const properties = propertiesOf(node)
      properties['data-block'] = offset
      properties['data-block-end'] = node.position.end.offset
    }
  }
}
