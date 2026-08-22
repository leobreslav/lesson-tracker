import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'

/**
 * Разбор одного скана на работы учеников.
 *
 * Экран, а не кнопка: где чья работа, видно только глазами. Титульный лист
 * человек узнаёт с одного взгляда, а машина — нет, и правило «каждая работа
 * два листа» ломается на первом же, кто взял третий, причём **молча**:
 * съезжает весь хвост, а на экране всё выглядит разобранным.
 *
 * Поэтому здесь границы ставит человек, а автоматика (QR на титульном
 * листе) когда-нибудь будет этот же экран предзаполнять — заменить его она
 * не сможет, потому что ошибаться будет тоже.
 *
 * Страницы рисует браузер: файл уже у человека в руках, а тащить на сервер
 * растеризатор ради превью незачем. `pdfjs-dist` грузится лениво — учитель,
 * который сюда не заходит, за неё не платит.
 *
 * Ошибка в разборе — это чужая контрольная у одноклассника, поэтому
 * отправить нельзя, пока хоть у одного куска нет имени, а уже разобранное
 * всегда переназначается одной кнопкой в таблице.
 */
export default function SplitDialog({ students, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [file, setFile] = useState(null)
  const [pages, setPages] = useState([]) // [{number, url}]
  const [starts, setStarts] = useState(new Set([1]))
  const [owners, setOwners] = useState({}) // номер первой страницы → ученик
  const [reading, setReading] = useState(false)
  const [error, setError] = useState(null)
  const drawn = useRef([])

  useEffect(
    () => () => drawn.current.forEach((url) => URL.revokeObjectURL(url)),
    [],
  )

  const read = async (chosen) => {
    if (!chosen) return

    setReading(true)
    setError(null)
    try {
      const pdfjs = await import('pdfjs-dist')
      // воркер тем же бандлом: внешние адреса запрещены и не нужны
      pdfjs.GlobalWorkerOptions.workerSrc = (
        await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
      ).default

      const data = new Uint8Array(await chosen.arrayBuffer())
      const book = await pdfjs.getDocument({ data }).promise
      const shots = []

      for (let number = 1; number <= book.numPages; number += 1) {
        const page = await book.getPage(number)
        // мелко: на экране это лист бумаги в спичечный коробок, и нужен он
        // затем, чтобы отличить титульный от прочих, а не читать его
        const viewport = page.getViewport({ scale: 0.35 })
        const canvas = document.createElement('canvas')
        canvas.width = viewport.width
        canvas.height = viewport.height
        await page.render({ canvasContext: canvas.getContext('2d'), viewport })
          .promise

        const url = await new Promise((resolve) =>
          canvas.toBlob((blob) => resolve(URL.createObjectURL(blob))),
        )
        drawn.current.push(url)
        shots.push({ number, url })
      }

      setFile(chosen)
      setPages(shots)
      setStarts(new Set([1]))
      setOwners({})
    } catch (err) {
      setError(t('split.unreadable'))
    } finally {
      setReading(false)
    }
  }

  /** Куски: от отмеченной страницы до следующей отмеченной. */
  const pieces = useMemo(() => {
    const marks = [...starts].sort((a, b) => a - b)

    return marks.map((first, index) => ({
      first,
      last: (marks[index + 1] ?? pages.length + 1) - 1,
      student: owners[first] ?? null,
    }))
  }, [starts, owners, pages.length])

  const taken = new Set(Object.values(owners).filter(Boolean))
  const ready = pieces.length > 0 && pieces.every((piece) => piece.student)

  const toggle = (number) => {
    if (number === 1) return // первая страница — всегда начало

    setStarts((current) => {
      const next = new Set(current)
      if (next.has(number)) next.delete(number)
      else next.add(number)
      return next
    })
  }

  const submit = (event) => {
    event.preventDefault()
    if (busy || !ready) return

    onSubmit({
      file,
      plan: pieces.map((piece) => ({
        student: piece.student,
        first: piece.first,
        last: piece.last,
      })),
    })
  }

  const pieceOf = (number) =>
    pieces.find((piece) => number >= piece.first && number <= piece.last)

  return (
    <Modal className="shelf" onClose={onClose} title={t('split.title')}>
      <form onSubmit={submit}>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {pages.length === 0 ? (
          <>
            <p className="hint">{t('split.pick')}</p>
            <div className="row">
              <input
                type="file"
                accept="application/pdf"
                aria-label={t('split.file')}
                disabled={reading}
                onChange={(event) => read(event.target.files?.[0])}
              />
            </div>
            {reading && <p className="hint">{t('split.reading')}</p>}
          </>
        ) : (
          <>
            <p className="hint">{t('split.howTo')}</p>

            <ol className="scan-pages">
              {pages.map((page) => {
                const piece = pieceOf(page.number)
                const opens = starts.has(page.number)

                return (
                  <li key={page.number} className={opens ? 'starts' : ''}>
                    <button
                      type="button"
                      className="page"
                      aria-pressed={opens}
                      title={t(opens ? 'split.notFirst' : 'split.markFirst')}
                      onClick={() => toggle(page.number)}
                    >
                      <img src={page.url} alt={`${page.number}`} />
                      <span className="number">{page.number}</span>
                    </button>
                    {opens && (
                      <select
                        value={owners[page.number] ?? ''}
                        aria-label={t('split.whose', { page: page.number })}
                        onChange={(event) =>
                          setOwners((current) => ({
                            ...current,
                            [page.number]: Number(event.target.value) || null,
                          }))
                        }
                      >
                        <option value="">{t('split.chooseStudent')}</option>
                        {students
                          .filter(
                            (student) =>
                              !taken.has(student.id) ||
                              owners[page.number] === student.id,
                          )
                          .map((student) => (
                            <option key={student.id} value={student.id}>
                              {student.name}
                            </option>
                          ))}
                      </select>
                    )}
                    {!opens && piece?.student && (
                      <span className="hint continues">{t('split.same')}</span>
                    )}
                  </li>
                )
              })}
            </ol>

            <p className="hint">
              {t('split.progress', {
                named: pieces.filter((piece) => piece.student).length,
                total: pieces.length,
              })}
              {students.length > taken.size && (
                <>
                  {' · '}
                  {t('split.without', { count: students.length - taken.size })}
                </>
              )}
            </p>
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !ready}>
            {t('split.submit')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
