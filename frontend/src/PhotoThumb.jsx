import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { photoUrl } from './api'
/* Ленивым этот импорт быть не может и не должен: просмотрщик тянет тот же
   модуль напрямую, так что в отдельный кусок он всё равно не уедет — сборка
   на это и ругается. Тяжёлый тут не он (пара килобайт), а сам `pdfjs`, и он
   грузится лениво внутри, при первом же PDF. */
import { book, drawPageOf } from './pdfPage'

/**
 * Снимок работы, показанный картинкой.
 *
 * Устроено ровно так же, как картинка в содержании урока (`LessonImage`), и
 * по той же причине: бакет приватный, адрес подписывается на пять минут, а
 * `<img>` спросить его не может — заголовок с токеном он не несёт и через
 * редирект на чужой домен заголовок всё равно не проходит. Спрашивает
 * страница, тег получает готовое.
 *
 * Адрес помнится чуть меньше, чем живёт. Без этого полоса из шести снимков
 * спрашивала бы шесть адресов при каждой перерисовке — а перерисовывается
 * страница ученика раз в три секунды опросом.
 *
 * Отдельный модуль от `LessonImage`, хотя приём один: там адресуется **файл**
 * (разметка называет объект в бакете, потому что переживает копирование
 * плана), здесь — **вложение** (у снимка копий не бывает, зато право на него
 * спрашивается по работе ученика). Сложить их значило бы завести функцию с
 * ветвлением по тому, что за число ей дали.
 */

// подписанная ссылка живёт пять минут; держим её чуть меньше
const KEEP = 4 * 60 * 1000

const known = new Map()

export function addressOf(photo) {
  const remembered = known.get(photo)
  if (remembered && Date.now() - remembered.at < KEEP) return remembered.asked

  // запоминается сама попытка, а не её итог: миниатюра и открытый
  // просмотрщик смотрят на один снимок, и спрашивать дважды незачем
  const asked = photoUrl(photo)
  asked.catch(() => known.delete(photo))
  known.set(photo, { at: Date.now(), asked })

  return asked
}

/** Забыть адрес: снимок убрали, и держать протухшую ссылку незачем. */
export function forgetPhoto(photo) {
  known.delete(photo)
}

export default function PhotoThumb({ photo, alt = '', className = '', pdf = false }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState(null)
  const [gone, setGone] = useState(false)

  /*
   * У PDF миниатюра — его **первая страница**, а не значок документа.
   *
   * Значок отвечает на вопрос «какого типа файл», а человек в этом месте
   * спрашивает другое: «чья это работа и та ли она». Стопка одинаковых
   * значков не отвечает ни на один из двух, и открывать пришлось бы каждый.
   *
   * Рисуется она тем же холстом, что и в просмотрщике, и отдаётся сюда
   * готовой картинкой: тег остаётся `<img>`, а с ним остаются и стили, и
   * ленивая загрузка, и поведение при пропаже файла.
   */
  useEffect(() => {
    let cancelled = false
    setGone(false)
    setUrl(null)

    addressOf(photo).then(
      async (address) => {
        if (cancelled) return
        if (!pdf) {
          setUrl(address)
          return
        }
        try {
          const document = await book(photo, address)
          const sheet = await drawPageOf(document, 0)
          if (!cancelled) setUrl(sheet.toDataURL('image/jpeg', 0.7))
        } catch {
          if (!cancelled) setGone(true)
        }
      },
      () => !cancelled && setGone(true),
    )

    return () => {
      cancelled = true
    }
  }, [photo, pdf])

  if (gone) {
    return <span className={`photo-thumb gone ${className}`.trim()}>⚠</span>
  }

  if (!url) {
    return (
      <span
        className={`photo-thumb waiting ${className}`.trim()}
        aria-label={t('common.loading')}
      />
    )
  }

  return (
    <img
      src={url}
      alt={alt}
      className={`photo-thumb ${className}`.trim()}
      onError={() => setGone(true)}
    />
  )
}
