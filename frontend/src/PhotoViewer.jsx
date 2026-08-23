import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import PhotoNoteThread from './PhotoNoteThread'
import { addressOf } from './PhotoThumb'
import {
  drawOnPhoto,
  fetchPhotoMarkup,
  pinPhotoNote,
  turnPhoto,
  undoOnPhoto,
} from './api'
import { layout, penPixels, step, toScreen, toSource, turn } from './photoGeometry'

/**
 * Просмотрщик работы: увидеть снимок, обвести ошибку, поговорить о месте.
 *
 * Одно окно на обе стороны. Учитель в нём размечает, семья смотрит — и
 * смотрит **то же самое**: два окна над одними данными разошлись бы в первой
 * же правке, а обнаружил бы это ученик, у которого пометка стоит не там, где
 * её ставили.
 *
 * Четыре решения, которые видно в коде.
 *
 * **Рисуем на холсте, а не поверх картинки слоями.** Картинка, поворот,
 * увеличение и мазки — это одно преобразование, применённое ко всему разом;
 * разложи их по CSS-трансформам и SVG поверх, и совпадать они будут ровно до
 * первого дробного масштаба. Считает преобразование `photoGeometry.js`, и
 * оно под узловыми тестами: ошибка тут не падает, а ставит пометку рядом.
 *
 * **Мазок уходит на сервер, как только его дорисовали.** Не по кнопке
 * «сохранить»: проверка, потерянная закрытой вкладкой, — худший вид потери,
 * потому что человек уверен, что сделал работу. Отсюда и отмена ходит на
 * сервер: снимать нечего, кроме того, что уже записано.
 *
 * **Поворот сохраняется.** Снятая боком тетрадь снята боком навсегда, и
 * поворот, живущий в состоянии вкладки, каждый учитель делал бы заново, а
 * ученик не увидел бы его вовсе.
 *
 * **Листается набор, а не всё подряд.** Открыли снимки задачи — листаются
 * они; открыли работу целиком — снимки работы. За «дальше» человек ждёт
 * следующую страницу той же тетради, а не что-нибудь ещё.
 */

// Палитра проверки: красный по умолчанию, потому что им и правят; синий и
// зелёный — чтобы отличать «ошибка» от «смотри сюда»; чёрный для дорисовок.
const COLOURS = ['#e11d48', '#2563eb', '#16a34a', '#111827']

// Толщина в тысячных ширины снимка (см. `works.PhotoStroke`). Три ступени, а
// не ползунок: ползунок требует прицеливания ради выбора из трёх.
const PENS = [4, 10, 24]

const ZOOM = { min: 1, max: 6, step: 1.4 }

export default function PhotoViewer({ photos, current, onClose, onChanged }) {
  const { t } = useTranslation()

  const [openId, setOpenId] = useState(current)
  const photo = photos.find((item) => item.id === openId) ?? photos[0] ?? null

  const [markup, setMarkup] = useState(null)
  const [picture, setPicture] = useState(null)
  const [box, setBox] = useState({ width: 0, height: 0 })
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [tool, setTool] = useState('hand')
  const [colour, setColour] = useState(COLOURS[0])
  const [pen, setPen] = useState(PENS[1])
  const [drawing, setDrawing] = useState(null)
  const [note, setNote] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const stage = useRef(null)
  const canvas = useRef(null)
  const dragging = useRef(null)

  const rotation = markup?.rotation ?? 0
  const mayDraw = Boolean(markup?.can_draw)

  /* --- что показываем --------------------------------------------------- */

  useEffect(() => {
    if (!photo) return undefined

    let cancelled = false
    setMarkup(null)
    setPicture(null)
    setZoom(1)
    setPan({ x: 0, y: 0 })
    setNote(null)

    fetchPhotoMarkup(photo.id).then(
      (answer) => !cancelled && setMarkup(answer),
      (problem) => !cancelled && setError(problem.message),
    )

    addressOf(photo.id).then(
      (url) => {
        const image = new Image()
        // размеры нужны до первой отрисовки: без них масштаб не посчитать, а
        // холст, нарисованный «пока по умолчанию», прыгает на глазах
        image.onload = () => !cancelled && setPicture(image)
        image.onerror = () => !cancelled && setError(t('photos.gone'))
        image.src = url
      },
      (problem) => !cancelled && setError(problem.message),
    )

    return () => {
      cancelled = true
    }
  }, [photo, t])

  useEffect(() => {
    const watched = stage.current
    if (!watched) return undefined

    const measure = () =>
      setBox({ width: watched.clientWidth, height: watched.clientHeight })

    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(watched)
    return () => observer.disconnect()
  }, [photo])

  // натуральный размер, а не `.width`: у элемента `<img>` тот отвечает «каким
  // его нарисовали», и стоит однажды задать ему размер стилем — масштаб
  // посчитается от него, а пометки лягут мимо
  const place = picture
    ? layout({
        box,
        image: { width: picture.naturalWidth, height: picture.naturalHeight },
        rotation,
        zoom,
        pan,
      })
    : { scale: 0, width: 0, height: 0, left: 0, top: 0 }

  /* --- отрисовка -------------------------------------------------------- */

  const paint = useCallback(() => {
    const sheet = canvas.current
    if (!sheet || !picture) return

    // на экране с удвоенными точками холст рисуется в удвоенном размере, а
    // размечается в обычных: без этого линия выглядит мыльной.
    //
    // Присваивание размера холсту **пересоздаёт буфер**, поэтому оно стоит
    // под условием: пока ведут перо, отрисовка идёт на каждое движение
    // мыши, и выделять память по сотне раз в секунду незачем.
    const ratio = window.devicePixelRatio || 1
    const wide = Math.round(box.width * ratio)
    const tall = Math.round(box.height * ratio)
    if (sheet.width !== wide || sheet.height !== tall) {
      sheet.width = wide
      sheet.height = tall
    }

    const ink = sheet.getContext('2d')
    ink.setTransform(ratio, 0, 0, ratio, 0, 0)
    ink.clearRect(0, 0, box.width, box.height)

    ink.save()
    ink.translate(place.left + place.width / 2, place.top + place.height / 2)
    ink.rotate((rotation * Math.PI) / 180)
    // после поворота на четверть стороны меняются местами, и рисовать
    // картинку надо в её собственных, а не в тех, что видно на экране
    const along = rotation % 180 === 0 ? place.width : place.height
    const across = rotation % 180 === 0 ? place.height : place.width
    ink.drawImage(picture, -along / 2, -across / 2, along, across)
    ink.restore()

    const strokes = [...(markup?.strokes ?? [])]
    if (drawing) strokes.push(drawing)

    ink.lineCap = 'round'
    ink.lineJoin = 'round'
    for (const stroke of strokes) {
      ink.strokeStyle = stroke.color
      ink.lineWidth = penPixels(stroke.width, place, rotation)
      ink.beginPath()
      stroke.points.forEach((point, index) => {
        const { x, y } = toScreen(point, place, rotation)
        if (index === 0) ink.moveTo(x, y)
        else ink.lineTo(x, y)
      })
      // точка — тоже мазок: ткнули пером и не повели
      if (stroke.points.length === 1) {
        const { x, y } = toScreen(stroke.points[0], place, rotation)
        ink.lineTo(x + 0.01, y)
      }
      ink.stroke()
    }
  }, [box, picture, place, rotation, markup, drawing])

  useEffect(() => {
    paint()
  }, [paint])

  /*
   * Колесо увеличивает, а не прокручивает окно.
   *
   * Слушатель вешается руками и с `passive: false`: React объявляет `wheel`
   * пассивным, а пассивному `preventDefault` не даётся — и страница уезжала
   * бы под курсором вместе с картинкой. Тот же приём, что у любого
   * просмотрщика карт.
   */
  useEffect(() => {
    const sheet = canvas.current
    if (!sheet) return undefined

    const wheel = (event) => {
      event.preventDefault()
      setZoom((was) => {
        const next = event.deltaY < 0 ? was * 1.15 : was / 1.15
        const held = Math.min(ZOOM.max, Math.max(ZOOM.min, next))
        if (held === ZOOM.min) setPan({ x: 0, y: 0 })
        return held
      })
    }

    sheet.addEventListener('wheel', wheel, { passive: false })
    return () => sheet.removeEventListener('wheel', wheel)
  }, [picture])

  /* --- перо, булавка и рука --------------------------------------------- */

  const at = (event) => {
    const frame = canvas.current.getBoundingClientRect()
    return toSource(
      { x: event.clientX - frame.left, y: event.clientY - frame.top },
      place,
      rotation,
    )
  }

  const down = (event) => {
    if (!picture) return
    event.currentTarget.setPointerCapture(event.pointerId)

    if (tool === 'pen' && mayDraw) {
      setDrawing({ color: colour, width: pen, points: [at(event)] })
      return
    }

    if (tool === 'note' && mayDraw) {
      // булавка ставится сразу, а слово к ней спрашивается на месте: окно
      // «введите текст» поверх окна означало бы непонятный Escape
      setNote({ fresh: at(event) })
      setTool('hand')
      return
    }

    // таскать нечего, пока картинка вписана целиком: сдвиг увёл бы её за
    // край, а вернуть было бы нечем — кнопки «на место» тут нет
    if (zoom > 1) {
      dragging.current = { x: event.clientX - pan.x, y: event.clientY - pan.y }
    }
  }

  const move = (event) => {
    if (drawing) {
      setDrawing((was) => {
        const point = at(event)
        // точки ближе полутысячной доли друг к другу мазок не меняют, а
        // складываются в тысячи: сервер такой мазок не примет (`MAX_POINTS`),
        // и узнал бы об этом учитель, уже проведя линию
        const last = was.points[was.points.length - 1]
        if (Math.hypot(point[0] - last[0], point[1] - last[1]) < 0.0005) return was
        return { ...was, points: [...was.points, point] }
      })
      return
    }
    if (dragging.current) {
      setPan({
        x: event.clientX - dragging.current.x,
        y: event.clientY - dragging.current.y,
      })
    }
  }

  const up = async () => {
    dragging.current = null
    if (!drawing) return

    const stroke = drawing
    setDrawing(null)
    setError(null)
    try {
      const saved = await drawOnPhoto(photo.id, stroke)
      setMarkup((was) => ({ ...was, strokes: [...was.strokes, saved] }))
      onChanged?.()
    } catch (problem) {
      setError(problem.message)
    }
  }

  const undo = async () => {
    setBusy(true)
    setError(null)
    try {
      await undoOnPhoto(photo.id)
      setMarkup(await fetchPhotoMarkup(photo.id))
      onChanged?.()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  const rotate = async (direction) => {
    const degrees = turn(rotation, direction)
    // поворот виден сразу, а запрос идёт следом: ждать ответа сервера,
    // чтобы увидеть повёрнутую картинку, — это полсекунды на каждое нажатие
    setMarkup((was) => ({ ...was, rotation: degrees }))
    setPan({ x: 0, y: 0 })
    try {
      await turnPhoto(photo.id, degrees)
      onChanged?.()
    } catch (problem) {
      setError(problem.message)
      setMarkup((was) => ({ ...was, rotation }))
    }
  }

  const pin = async (text) => {
    const [x, y] = note.fresh
    setBusy(true)
    try {
      const saved = await pinPhotoNote(photo.id, { x, y, text })
      setMarkup((was) => ({ ...was, notes: [...was.notes, saved] }))
      setNote({ id: saved.id })
      onChanged?.()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  const flip = (direction) => {
    const next = step(photos, photo?.id, direction)
    if (next) setOpenId(next.id)
  }

  if (!photo) return null

  const pinned = markup?.notes ?? []
  const opened = pinned.find((item) => item.id === note?.id) ?? null

  return (
    <Modal
      onClose={onClose}
      className="photo-viewer"
      title={photo.title}
      actions={
        photos.length > 1 && (
          <span className="photo-paging">
            <button type="button" className="link" onClick={() => flip(-1)}>
              ‹
            </button>
            <span className="hint">
              {t('photos.position', {
                at: photos.findIndex((item) => item.id === photo.id) + 1,
                of: photos.length,
              })}
            </span>
            <button type="button" className="link" onClick={() => flip(1)}>
              ›
            </button>
          </span>
        )
      }
    >
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="photo-tools">
        <button type="button" className="compact" onClick={() => rotate('ccw')}>
          ↺
        </button>
        <button type="button" className="compact" onClick={() => rotate('cw')}>
          ↻
        </button>
        <button
          type="button"
          className="compact"
          disabled={zoom <= ZOOM.min}
          onClick={() => {
            setZoom((was) => Math.max(ZOOM.min, was / ZOOM.step))
            setPan({ x: 0, y: 0 })
          }}
        >
          −
        </button>
        <span className="hint">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="compact"
          disabled={zoom >= ZOOM.max}
          onClick={() => setZoom((was) => Math.min(ZOOM.max, was * ZOOM.step))}
        >
          +
        </button>

        {mayDraw && (
          <>
            <span className="photo-tools-gap" />
            {/* три органа одного разговора: чем рисуем, каким цветом и
                какой толщины. Перо выключается тем же нажатием — иначе
                рука превращается в отдельную кнопку ради выхода из режима */}
            <button
              type="button"
              className={`compact${tool === 'pen' ? ' on' : ''}`}
              onClick={() => setTool(tool === 'pen' ? 'hand' : 'pen')}
            >
              {t('photos.pen')}
            </button>
            <button
              type="button"
              className={`compact${tool === 'note' ? ' on' : ''}`}
              onClick={() => setTool(tool === 'note' ? 'hand' : 'note')}
            >
              {t('photos.note')}
            </button>
            {COLOURS.map((one) => (
              <button
                key={one}
                type="button"
                className={`photo-colour${one === colour ? ' on' : ''}`}
                style={{ background: one }}
                title={t('photos.colour')}
                aria-label={t('photos.colour')}
                onClick={() => {
                  setColour(one)
                  setTool('pen')
                }}
              />
            ))}
            {PENS.map((one) => (
              <button
                key={one}
                type="button"
                className={`photo-pen${one === pen ? ' on' : ''}`}
                title={t('photos.width')}
                aria-label={t('photos.width')}
                onClick={() => {
                  setPen(one)
                  setTool('pen')
                }}
              >
                <i style={{ width: `${one / 2 + 2}px`, height: `${one / 2 + 2}px` }} />
              </button>
            ))}
            <button
              type="button"
              className="compact"
              disabled={busy || !(markup?.strokes ?? []).length}
              onClick={undo}
            >
              {t('photos.undo')}
            </button>
          </>
        )}
      </div>

      <div className="photo-stage" ref={stage}>
        <canvas
          ref={canvas}
          className={`photo-canvas ${tool}`}
          style={{ width: box.width, height: box.height }}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={up}
          onPointerCancel={up}
        />

        {/* булавки — обычные кнопки поверх холста, а не рисунок на нём:
            по нарисованному не кликнуть, а разговор начинается именно с
            нажатия на конкретное место */}
        {picture &&
          pinned.map((item, index) => {
            const at = toScreen([item.x, item.y], place, rotation)
            return (
              <button
                key={item.id}
                type="button"
                className={`photo-pin${note?.id === item.id ? ' on' : ''}`}
                style={{ left: at.x, top: at.y }}
                onClick={() => setNote({ id: item.id })}
              >
                {index + 1}
              </button>
            )
          })}

        {note?.fresh && picture && (
          <span
            className="photo-pin fresh"
            style={{
              left: toScreen(note.fresh, place, rotation).x,
              top: toScreen(note.fresh, place, rotation).y,
            }}
          >
            +
          </span>
        )}

        {!picture && <p className="hint">{t('common.loading')}</p>}
      </div>

      {(opened || note?.fresh) && (
        <PhotoNoteThread
          note={opened}
          busy={busy}
          mayRemove={mayDraw}
          onPin={pin}
          onSaid={(updated) =>
            setMarkup((was) => ({
              ...was,
              notes: was.notes.map((one) => (one.id === updated.id ? updated : one)),
            }))
          }
          onRemoved={(id) => {
            setMarkup((was) => ({
              ...was,
              notes: was.notes.filter((one) => one.id !== id),
            }))
            setNote(null)
            onChanged?.()
          }}
          onClose={() => setNote(null)}
        />
      )}
    </Modal>
  )
}
