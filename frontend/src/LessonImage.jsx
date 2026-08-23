import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchImageUrl } from './api'

/**
 * A picture written into lesson content, put on the screen.
 *
 * The bucket is private, so there is no address to write into the Markdown —
 * only a signed one, good for five minutes, and it has to be asked for. An
 * `<img>` cannot ask: it sends no Authorization header and a header does not
 * survive the redirect to R2 anyway. So the page asks, and hands the answer
 * to the tag. Same reasoning as `openAttachment`, one step further.
 *
 * The address is remembered for a little less than it lives. Without that,
 * every keystroke in the editor below would re-mount the picture and ask
 * again — a request per character, for a link that has not expired.
 *
 * Anything that is not one of ours (`file:12`) is drawn as written: content
 * may perfectly well carry a picture from the web.
 */

const OURS = /^file:(\d+)$/

// подписанная ссылка живёт пять минут (`FILE_URL_TTL`); держим её чуть
// меньше, чтобы не подставить в `src` адрес, протухший по дороге
const KEEP = 4 * 60 * 1000

const known = new Map()

/** The file this address names, or null if it names something else. */
export function imageFile(src) {
  const match = OURS.exec((src ?? '').trim())
  return match ? Number(match[1]) : null
}

function addressOf(file) {
  const remembered = known.get(file)
  if (remembered && Date.now() - remembered.at < KEEP) return remembered.asked

  // сама попытка, а не её итог: две картинки одного файла на странице —
  // обычное дело, и спрашивать адрес дважды незачем
  const asked = fetchImageUrl(file).then(({ url }) => url)
  asked.catch(() => known.delete(file))
  known.set(file, { at: Date.now(), asked })

  return asked
}

export default function LessonImage({ src, alt = '', node, ...rest }) {
  const { t } = useTranslation()
  const file = imageFile(src)
  const [url, setUrl] = useState(null)
  const [gone, setGone] = useState(false)

  useEffect(() => {
    if (file === null) return undefined

    let cancelled = false
    setGone(false)
    addressOf(file).then(
      (address) => !cancelled && setUrl(address),
      () => !cancelled && setGone(true),
    )

    return () => {
      cancelled = true
    }
  }, [file])

  if (file === null) return <img src={src} alt={alt} {...rest} />

  // Отказ рисуется на месте картинки, а не пустотой: содержание урока могло
  // приехать с чужой полки, и «картинку не показать» — это ответ, а дырка в
  // тексте выглядит как поломанная страница
  if (gone) {
    return (
      <span {...rest} className={`${rest.className ?? ''} gone`.trim()}>
        {t('lesson.image.gone')}
      </span>
    )
  }

  if (!url) {
    return (
      <span
        {...rest}
        className={`${rest.className ?? ''} waiting`.trim()}
        aria-label={t('common.loading')}
      />
    )
  }

  // Адрес дали, а картинка по нему не открылась — ссылка успела протухнуть,
  // объект унесла уборка. Отвечает на это `onError`, а не молчание: у
  // картинки с пустым `alt` сломанный `<img>` схлопывается в ноль пикселей,
  // то есть пропадает вместе с местом, за которое её можно взять
  return (
    <img src={url} alt={alt} {...rest} onError={() => setGone(true)} />
  )
}
