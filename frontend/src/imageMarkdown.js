/**
 * An image inside lesson content: how it is written down, and how it moves.
 *
 * The content is Markdown and stays Markdown — that is the rule this whole
 * area rests on, and it is why there is no WYSIWYG editor here. An image
 * therefore has to be expressible *as text*, including the two things a
 * person wants to change about it once it is in: how big it is and where it
 * sits relative to the words.
 *
 * So the notation is Pandoc's, not one of our own:
 *
 *     ![](file:12){width=320 .right}
 *
 * A plain Markdown image with an attribute block after it. Every Markdown
 * parser reads the image; Pandoc reads the attributes too, which is what
 * keeps the export-into-LaTeX promise alive — a size written this way
 * survives the trip, and a size written into a URL fragment would not.
 *
 * The address names the **file** rather than the attachment pointing at it.
 * One image lives in as many `Attachment` rows as there are copies of the
 * plan, each with an id of its own, and restoring a snapshot mints new ones
 * again; text naming the attachment would have to be rewritten at every one
 * of those places, and the first forgotten one would break a picture in
 * silence. See `plans.content.IMAGE_REF` on the server for the other half.
 *
 * Everything below is a pure string function, and that is deliberate: this
 * is the part that must not be guessed at, so it is the part under test.
 */

/** Where an image stands relative to the text around it. */
export const PLACEMENTS = ['block', 'left', 'center', 'right']

const DEFAULT = { alt: '', width: null, placement: 'block' }

const token = () => /!\[([^\]]*)\]\(\s*file:(\d+)\s*\)(?:\{([^}]*)\})?/g

/**
 * Blank lines are how Markdown separates blocks, so three of them are two.
 *
 * Trailing whitespace is left alone on purpose: two spaces at the end of a
 * line are a hard line break, and tidying them away would quietly rewrite
 * somebody's poem.
 */
const tidy = (text) => text.replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '')

/** `{width=320 .right}` → what it means. Anything unknown is ignored. */
export function parseAttrs(raw = '') {
  const width = /(?:^|\s)width\s*=\s*(\d+)/.exec(raw || '')
  const placement = PLACEMENTS.filter((name) => name !== 'block').find((name) =>
    new RegExp(`(?:^|\\s)\\.${name}(?=\\s|$)`).test(raw || ''),
  )

  return {
    width: width ? Number(width[1]) : null,
    placement: placement ?? 'block',
  }
}

/** The same the other way round; nothing to say means no braces at all. */
export function formatAttrs({ width = null, placement = 'block' } = {}) {
  const parts = []
  if (width) parts.push(`width=${Math.round(width)}`)
  if (placement && placement !== 'block') parts.push(`.${placement}`)

  return parts.length ? `{${parts.join(' ')}}` : ''
}

export function imageToken(image) {
  const { alt, file, width, placement } = { ...DEFAULT, ...image }
  return `![${alt}](file:${file})${formatAttrs({ width, placement })}`
}

/**
 * Every image in a piece of content, in the order it is written.
 *
 * `start` and `end` are what makes the rest of this module possible: the
 * rendered picture carries its own start offset (see `markdownImages.js`),
 * so a click on the screen finds the exact characters it came from.
 */
export function findImages(text = '') {
  const found = []
  const pattern = token()
  let match

  while ((match = pattern.exec(text ?? '')) !== null) {
    const [raw, alt, file, attrs] = match
    found.push({
      start: match.index,
      end: match.index + raw.length,
      raw,
      alt,
      file: Number(file),
      ...parseAttrs(attrs),
    })
  }

  return found
}

/** The image written at this offset, if that is where one starts. */
export const imageAt = (text, offset) =>
  findImages(text).find((image) => image.start === Number(offset)) ?? null

/**
 * Put a token in as a paragraph of its own, wherever the caret happens to be.
 *
 * Always its own paragraph, never inside a sentence, and that is a decision
 * rather than an implementation detail: a picture that can sit anywhere is a
 * picture that cannot be moved anywhere without deciding what to do with the
 * half-sentence around it. Standing alone, it has one obvious place before
 * and one after every block — which is exactly what dragging it needs.
 *
 * Floating does not suffer from this: `.left` and `.right` make the *next*
 * paragraph flow around the picture, and a sibling is all that takes.
 */
export function insertAsBlock(text = '', at = null, piece) {
  const source = text ?? ''
  const cut = Math.max(0, Math.min(at ?? source.length, source.length))
  const before = source.slice(0, cut)
  const after = source.slice(cut)

  // as many newlines as it takes to stand alone, and not one more
  const lead = !before
    ? ''
    : before.endsWith('\n\n')
      ? ''
      : before.endsWith('\n')
        ? '\n'
        : '\n\n'
  const tail = !after
    ? ''
    : after.startsWith('\n\n')
      ? ''
      : after.startsWith('\n')
        ? '\n'
        : '\n\n'

  const head = before + lead + piece

  return { text: head + tail + after, caret: head.length }
}

/**
 * Take the token out — along with one blank line, when it stood alone.
 *
 * Without that, removing the picture leaves the two blank lines that used to
 * fence it off and they become an empty paragraph: invisible on the page,
 * plain to see in the text, and growing by two characters every time
 * somebody drags the picture somewhere. Which separator goes depends on
 * which side has one, hence the two branches rather than a blanket trim.
 *
 * Reports where the cut began and how long it was, because a move has to
 * correct its target by exactly this much.
 */
function excise(text, image) {
  let start = image.start
  let end = image.end
  const before = text.slice(0, start)
  const after = text.slice(end)
  const lead = /\n[ \t]*\n[ \t]*$/.exec(before)
  const tail = /^[ \t]*\n[ \t]*\n/.exec(after)

  if ((lead || !before) && (tail || !after)) {
    if (tail) end += tail[0].length
    else if (lead) start -= lead[0].length
  }

  return {
    text: text.slice(0, start) + text.slice(end),
    start,
    removed: end - start,
  }
}

/** The text without this image, and without the hole it leaves behind. */
export const removeImage = (text, image) => tidy(excise(text, image).text)

/** The same image, written differently: another size, another placement. */
export function writeImage(text, image, changes) {
  const piece = imageToken({ ...image, ...changes })
  return text.slice(0, image.start) + piece + text.slice(image.end)
}

/**
 * Carry an image to another place in the text.
 *
 * `at` is an offset in the text as it is *now* — the start of the block the
 * picture is being dropped in front of, or the end of everything. Taking the
 * token out shifts every offset after it, so the target is corrected before
 * the insert rather than after: correcting after would have to guess whether
 * the caller meant the old text or the new one.
 */
export function moveImage(text, image, at) {
  const piece = text.slice(image.start, image.end)
  const cut = excise(text, image)
  const target =
    at <= cut.start
      ? at
      : Math.max(cut.start, Math.min(at - cut.removed, cut.text.length))

  return tidy(insertAsBlock(cut.text, target, piece).text)
}
