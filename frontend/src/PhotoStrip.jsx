import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import PhotoThumb, { forgetPhoto } from './PhotoThumb'
import { formatSize, iconFor } from './fileKind'
import { openAttachment } from './api'

/**
 * Полоса снимков одного места: тетрадь по задаче или по работе целиком.
 *
 * Один компонент на четыре экрана — страница ученика, история ячейки, работа
 * ученика у учителя и просмотр родителем, — и это не экономия строк. Полоса
 * отвечает на один и тот же вопрос («что сюда приложено»), и четыре её копии
 * разъехались бы в первой же правке: где-то появилась бы пометка о проверке,
 * где-то нет, и учитель с учеником смотрели бы на разное.
 *
 * Три решения внутри.
 *
 * **Не всё, что приложено, — картинка.** Разрезанный PDF от учителя лежит на
 * той же строке, что снимок с телефона; просмотрщик умеет только второе.
 * Поэтому вид выбирается по `image`, а не по надежде: файл, который нельзя
 * нарисовать, показывается строкой со скрепкой и скачивается, как раньше.
 *
 * **Загрузка идёт сразу и по одному файлу.** Выбрали шесть кадров — уходит
 * шесть запросов, и каждый появляется в полосе, как только доехал. Пачкой
 * одним запросом это было бы «всё или ничего»: отвалившийся на пятом кадре
 * интернет терял бы и первые четыре, а телефон в школьном коридоре
 * отваливается постоянно.
 *
 * **Проверенный снимок виден до открытия.** У миниатюры стоит пометка, если
 * на снимке есть обводка или заметки: иначе проверенная тетрадь неотличима
 * от непроверенной, и открывать пришлось бы каждую.
 */
export default function PhotoStrip({
  photos = [],
  onOpen,
  onSend = null,
  onRemove = null,
  // Кого этот человек вправе снять. Вопрос **к снимку**, а не к полосе: на
  // работе ученика вперемешку лежат его собственные фотографии и скан от
  // учителя, и крестик над чужим был бы кнопкой, которая ничего не делает,
  // — хуже, чем её отсутствие. Право считает сервер (`mine`), здесь показ.
  removable = () => true,
  label = null,
  hint = null,
}) {
  const { t } = useTranslation()
  const picker = useRef(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)

  const send = async (files) => {
    const pictures = [...files].filter((file) => file.type.startsWith('image/'))
    if (!pictures.length || !onSend) return

    setBusy(true)
    setError(null)
    try {
      // по одному и по порядку: так первый кадр виден, пока едет последний
      for (const file of pictures) await onSend(file)
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  const drop = (event) => {
    event.preventDefault()
    setDragging(false)
    send(event.dataTransfer.files)
  }

  const remove = async (photo) => {
    setError(null)
    try {
      await onRemove(photo)
      forgetPhoto(photo.id)
    } catch (problem) {
      setError(problem.message)
    }
  }

  if (!photos.length && !onSend) return null

  return (
    <section className="photo-strip">
      {label && <span className="hint">{label}</span>}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <ul className="photos">
        {photos.map((photo) =>
          /* плиткой показывается всё, что просмотрщик умеет открыть, — и
             снимок, и PDF: у второго миниатюрой служит первая страница */
          (photo.viewable ?? photo.image) ? (
            <li key={photo.id} className="photo">
              <button
                type="button"
                className="photo-open"
                title={photo.title}
                onClick={() => onOpen(photo)}
              >
                <PhotoThumb photo={photo.id} alt={photo.title} pdf={photo.pdf} />
                {/* обводка или заметки на снимке: без пометки проверенная
                    тетрадь неотличима от непроверенной */}
                {(photo.notes > 0 || photo.strokes > 0) && (
                  <i className="marked" aria-hidden="true">
                    ✎{photo.notes > 0 ? photo.notes : ''}
                  </i>
                )}
              </button>
              {onRemove && removable(photo) && (
                <button
                  type="button"
                  className="link remove"
                  title={t('common.delete')}
                  disabled={busy}
                  onClick={() => remove(photo)}
                >
                  ✕
                </button>
              )}
            </li>
          ) : (
            /* Не картинка — строкой со скрепкой, как любое другое вложение.
               Таких два вида, и вести себя они обязаны по-разному: файл
               (разрезанный PDF от учителя) скачивается через подписанный
               адрес, а приложенный **адрес** открывается как есть — за ним
               не наш бакет, а чужой документ или разбор на видео.

               Кнопка на месте ссылки была бы не косметической ошибкой:
               скачивание отвечает такому вложению отказом, и приложенная
               ссылка молча перестала бы открываться у кого бы то ни было. */
            <li key={photo.id} className="photo file">
              <span aria-hidden="true">{iconFor(photo)}</span>
              {photo.kind === 'link' ? (
                <a
                  href={photo.url}
                  target="_blank"
                  rel="noreferrer"
                  className="title"
                >
                  {photo.title}
                </a>
              ) : (
                <button
                  type="button"
                  className="link title"
                  onClick={() => openAttachment(photo.id)}
                >
                  {photo.title}
                </button>
              )}
              {sizeOf(photo, t)}
              {onRemove && removable(photo) && (
                <button
                  type="button"
                  className="link remove"
                  title={t('common.delete')}
                  disabled={busy}
                  onClick={() => remove(photo)}
                >
                  ✕
                </button>
              )}
            </li>
          ),
        )}
      </ul>

      {onSend && (
        <div
          className={`photo-drop${dragging ? ' over' : ''}`}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
        >
          {/* зона и кнопка — один орган, как в панели урока: тащить умеют не
              все и не везде, а нажать — везде. На телефоне это же нажатие
              открывает камеру */}
          <button
            type="button"
            className="link"
            disabled={busy}
            onClick={() => picker.current?.click()}
          >
            {busy ? t('photos.sending') : t('photos.add')}
          </button>
          {hint && <span className="hint"> {hint}</span>}
          <input
            ref={picker}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(event) => {
              send(event.target.files)
              // тот же файл, выбранный второй раз, иначе не даёт события
              event.target.value = ''
            }}
          />
        </div>
      )}
    </section>
  )
}

function sizeOf(photo, t) {
  const size = formatSize(photo.size)
  if (!size) return null
  return <span className="hint">{t(`lesson.size.${size.unit}`, size)}</span>
}
