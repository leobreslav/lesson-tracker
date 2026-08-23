import { useCallback, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import LessonImage from './LessonImage'
import Rendered from './Markdown'
import { uploadAttachment } from './api'
import {
  PLACEMENTS,
  findImages,
  imageToken,
  insertAsBlock,
  moveImage,
  removeImage,
  writeImage,
} from './imageMarkdown'

/**
 * Одно поле содержания: текст сверху, картинки под ним.
 *
 * Поле остаётся полем — Markdown правится как Markdown, и редактора,
 * владеющего разметкой, здесь по-прежнему нет: текст обязан пережить
 * экспорт в LaTeX, а WYSIWYG тихо лишил бы его этой возможности
 * (`plans/content.py`).
 *
 * Но картинку в тексте **не видно**: в поле она строка `![](file:12)`, и
 * ни размера у неё, ни места среди абзацев по этой строке не выбрать. Ровно
 * это и добавляет вид под полем: те же самые буквы, нарисованные, — и
 * картинка в нём тянется за угол, перетаскивается между абзацами и меняет
 * обтекание. Каждое движение возвращается в поле разметкой, и текст
 * остаётся единственным источником правды: у картинки нет состояния,
 * которого нет в буквах.
 *
 * Отсюда три следствия, каждое проверялось руками:
 *
 * * **вид появляется, только когда в тексте есть картинка.** Урок из одних
 *   слов выглядит ровно так, как выглядел, — иначе каждое поле удвоилось бы
 *   ради возможности, которой в нём не пользуются;
 * * **это не «Просмотр».** Тумблер в шапке замораживает панель целиком, и
 *   правка там обещала бы то, чего не будет. Здесь наоборот: правка идёт, и
 *   вид — её часть;
 * * **мышь ничего не открывает единолично.** Всё, что делает перетаскивание,
 *   выражается буквами в поле сверху — оно и есть путь с клавиатуры.
 *
 * Картинка всегда встаёт **отдельным абзацем** (`imageMarkdown.js`): так у
 * неё есть ровно одно место перед каждым блоком и одно после, а обтекание
 * `.left`/`.right` соседний абзац всё равно обтекает.
 */

// с чем браузер отдаёт картинку из буфера обмена и что примет сервер
const EXTENSION = {
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/gif': '.gif',
  'image/webp': '.webp',
}

const IMAGE_NAME = /\.(png|jpe?g|gif|webp)$/i

// меньше этого картинка перестаёт быть картинкой и становится опечаткой
const MIN_WIDTH = 48

const imagesIn = (source) =>
  [...(source?.files ?? [])].filter((file) => file.type?.startsWith('image/'))

/**
 * Имя с расширением — потому что на расширении держится проверка сервера.
 *
 * Из буфера обмена файл приезжает без имени вовсе или под чужим (`image.png`
 * у любого снимка экрана), и второе не хуже первого: имя едет в
 * `Content-Disposition`, то есть однажды окажется у человека в загрузках.
 */
const named = (file) => {
  const extension = EXTENSION[file.type]
  if (!extension) return file
  if (file.name && IMAGE_NAME.test(file.name)) return file

  return new File([file], `pasted-${Date.now()}${extension}`, { type: file.type })
}

/**
 * Картинка в виде под полем: сама картинка, ручка размера и ряд кнопок.
 *
 * Обёртка — `span`, а не `div`, и это не придирка: картинка стоит внутри
 * абзаца, а `div` внутри `<p>` браузер закрывает досрочно и разваливает
 * разметку. Обтекание на `span` с `display: inline-block` работает так же.
 */
function Framed({ image, chosen, act, ...picture }) {
  const { t } = useTranslation()

  // разметка не разобралась — рисуем картинку и ничего не обещаем
  if (!image) return <LessonImage {...picture} />

  const classes = ['md-image-frame', `md-image-${image.placement}`]
  if (chosen) classes.push('chosen')

  return (
    <span
      className={classes.join(' ')}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = 'move'
        // Firefox не начинает перетаскивание, пока в нём ничего не лежит,
        // а класть туда саму разметку нельзя: она высыпалась бы в любое
        // поле ввода, над которым картинку отпустят мимо
        event.dataTransfer.setData('text/plain', '')
        act.pick(image)
      }}
      onDragEnd={() => act.drop()}
      onClick={(event) => {
        event.stopPropagation()
        act.choose(image)
      }}
    >
      <LessonImage {...picture} />

      {chosen && (
        <span className="md-image-tools" role="group" aria-label={t('lesson.image.tools')}>
          {PLACEMENTS.map((placement) => (
            <button
              key={placement}
              type="button"
              className={placement === image.placement ? 'chosen' : ''}
              title={t(`lesson.image.place.${placement}`)}
              aria-label={t(`lesson.image.place.${placement}`)}
              aria-pressed={placement === image.placement}
              onClick={(event) => {
                event.stopPropagation()
                act.place(image, placement)
              }}
            >
              {t(`lesson.image.mark.${placement}`)}
            </button>
          ))}
          <button
            type="button"
            className="remove"
            title={t('lesson.image.remove')}
            aria-label={t('lesson.image.remove')}
            onClick={(event) => {
              event.stopPropagation()
              act.remove(image)
            }}
          >
            ✕
          </button>
        </span>
      )}

      <span
        className="md-image-grip"
        title={t('lesson.image.resize')}
        onPointerDown={(event) => act.resize(event, image)}
      />
    </span>
  )
}

export default function MarkdownField({
  value,
  onChange,
  rows = 4,
  label,
  placeholder,
  planRow = null,
  templateRow = null,
  /**
   * Владелец, которого в момент вставки ещё нет.
   *
   * Урок и строка полки существуют раньше своего текста — их правят, уже
   * заведёнными. А пояснения к работе пишут **в окне создания**, где работы
   * ещё нет ни одной строкой, и приложить картинку не к чему. Поэтому окно
   * умеет завести её по требованию и вернуть сюда владельца; здесь же — то
   * место, где это требование возникает.
   *
   * Возвращает то же, что принимает загрузка: `{ work }`, `{ planRow }` и
   * так далее. Отказ (не заполнено название) прилетает исключением и
   * показывается строкой ошибки — как и любой другой отказ загрузки.
   */
  ensureOwner = null,
  disabled = false,
}) {
  const { t } = useTranslation()

  const area = useRef(null)
  const pane = useRef(null)
  // текст в момент события, а не в момент отрисовки: между вставкой и
  // ответом сервера человек продолжает печатать, и написанное им терять
  // нельзя
  const latest = useRef(value)
  latest.current = value

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [chosen, setChosen] = useState(null)
  const [dragged, setDragged] = useState(null)
  const [drop, setDrop] = useState(null)

  const images = useMemo(() => findImages(value), [value])

  const put = useCallback(
    (text) => {
      latest.current = text
      onChange(text)
    },
    [onChange],
  )

  // --- вставка ---

  const take = async (files, at) => {
    setBusy(true)
    setError(null)

    let caret = at
    try {
      // владельца спрашиваем **до** первого файла и один раз на всю пачку:
      // иначе три вставленных снимка завели бы три работы
      const owner = ensureOwner ? await ensureOwner() : { planRow, templateRow }

      for (const file of files) {
        const added = await uploadAttachment({
          ...owner,
          file: named(file),
          inline: true,
        })

        const written = insertAsBlock(
          latest.current,
          Math.min(caret, latest.current.length),
          imageToken({ file: added.file }),
        )
        put(written.text)
        caret = written.caret
      }

      requestAnimationFrame(() => {
        area.current?.focus()
        area.current?.setSelectionRange(caret, caret)
      })
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  const paste = (event) => {
    const files = imagesIn(event.clipboardData)
    if (!files.length) return

    // текст из буфера вставляется как вставлялся: перехватываем только
    // картинку, и только когда она там действительно есть
    event.preventDefault()
    take(files, event.target.selectionStart)
  }

  const dropFile = (event) => {
    // своя же картинка, отпущенная мимо вида: в поле ей делать нечего
    if (dragged) {
      event.preventDefault()
      return
    }

    const files = imagesIn(event.dataTransfer)
    if (!files.length) return

    event.preventDefault()
    take(files, area.current?.selectionStart ?? latest.current.length)
  }

  // --- правка картинки ---

  /**
   * Размер тянется за угол, а в разметку уезжает один раз — по отпусканию.
   *
   * Пока тянут, ширина ставится прямо элементу: писать её в текст на каждом
   * движении значило бы перебирать Markdown заново шестьдесят раз в секунду
   * и класть в отмену шестьдесят состояний вместо одного.
   */
  const resize = (event, image) => {
    // без этого начнётся перетаскивание рамки: ручка лежит внутри неё
    event.preventDefault()
    event.stopPropagation()

    const frame = event.currentTarget.closest('.md-image-frame')
    const picture = frame?.querySelector('img')
    if (!picture) return

    const startX = event.clientX
    const startWidth = picture.getBoundingClientRect().width
    const room = pane.current?.clientWidth ?? Number.MAX_SAFE_INTEGER
    let width = Math.round(startWidth)

    const drag = (moved) => {
      width = Math.round(
        Math.min(Math.max(startWidth + moved.clientX - startX, MIN_WIDTH), room),
      )
      picture.style.width = `${width}px`
    }

    const done = () => {
      window.removeEventListener('pointermove', drag)
      window.removeEventListener('pointerup', done)
      picture.style.width = ''
      put(writeImage(latest.current, image, { width }))
    }

    window.addEventListener('pointermove', drag)
    window.addEventListener('pointerup', done)
  }

  /** Куда встанет картинка, если отпустить её здесь. */
  const spotAt = (y) => {
    const box = pane.current
    if (!box) return null

    const blocks = [...box.querySelectorAll('[data-block]')]
    const frame = box.getBoundingClientRect()

    // вид прокручивается, а черта лежит в нём же: без прокрутки она
    // рисовалась бы там, где абзац виден, а не там, где он стоит
    const shift = box.scrollTop - frame.top

    for (const block of blocks) {
      const rect = block.getBoundingClientRect()
      if (y < rect.top + rect.height / 2) {
        return { at: Number(block.dataset.block), top: rect.top + shift }
      }
    }

    const last = blocks[blocks.length - 1]
    if (!last) return null

    return {
      at: Number(last.dataset.blockEnd),
      top: last.getBoundingClientRect().bottom + shift,
    }
  }

  const act = useMemo(
    () => ({
      choose: (image) =>
        setChosen((current) => (current === image.start ? null : image.start)),
      pick: setDragged,
      // перетаскивание кончилось — где бы его ни отпустили. Без этого
      // черта «встанет сюда» оставалась бы висеть после броска мимо
      drop: () => {
        setDragged(null)
        setDrop(null)
      },
      place: (image, placement) => put(writeImage(latest.current, image, { placement })),
      remove: (image) => {
        setChosen(null)
        put(removeImage(latest.current, image))
      },
      resize,
    }),
    [put],
  )

  // Свежее состояние для картинки — ссылкой, а не замыканием: см. ниже
  const live = useRef(null)
  live.current = { images, chosen, act }

  /**
   * Компонент картинки создаётся **один раз** за жизнь поля.
   *
   * Пересоздать его — значит для React'а сменить тип узла, то есть
   * размонтировать и смонтировать картинку заново. А делалось бы это на
   * каждое нажатие клавиши: `images` пересчитываются от текста, и объект с
   * компонентами вместе с ними. Наружу это выходит миганием картинки при
   * наборе и новым запросом за адресом на каждую букву — по три подряд в
   * первом же браузерном прогоне.
   *
   * Свежее он берёт из ссылки, и это не хитрость: перерисовку вызывает
   * перерисовка самого поля, а к моменту вызова в ссылке уже новое.
   */
  const components = useMemo(
    () => ({
      img: function ContentImage(props) {
        const { images, chosen, act } = live.current
        const offset = Number(props['data-offset'])
        const image = images.find((found) => found.start === offset) ?? null

        return (
          <Framed
            {...props}
            image={image}
            chosen={image !== null && chosen === image.start}
            act={act}
          />
        )
      },
    }),
    [],
  )

  return (
    <div className="md-field">
      <textarea
        ref={area}
        value={value}
        rows={rows}
        spellCheck
        aria-label={label}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => put(event.target.value)}
        onPaste={paste}
        onDragOver={(event) => imagesIn(event.dataTransfer).length && event.preventDefault()}
        onDrop={dropFile}
      />

      {busy && (
        <p className="hint" role="status">
          {t('lesson.image.uploading')}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {images.length > 0 && (
        <div
          ref={pane}
          className="md-canvas"
          onClick={() => setChosen(null)}
          onDragOver={(event) => {
            if (!dragged) return
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
            setDrop(spotAt(event.clientY))
          }}
          onDragLeave={(event) => {
            // переход между абзацами внутри вида — не уход из него
            if (!event.currentTarget.contains(event.relatedTarget)) setDrop(null)
          }}
          onDrop={(event) => {
            if (!dragged || !drop) return
            event.preventDefault()
            put(moveImage(latest.current, dragged, drop.at))
            setChosen(null)
            act.drop()
          }}
        >
          <p className="hint md-canvas-hint">{t('lesson.image.hint')}</p>
          <Rendered text={value} blocks components={components} className="markdown md-live" />
          {drop && <span className="md-drop" style={{ top: `${drop.top}px` }} />}
        </div>
      )}
    </div>
  )
}
