import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import {
  applyScan,
  editScanPage,
  fetchScale,
  fetchScanState,
  markHeaderless,
  readScanPage,
  resetScan,
  saveScale,
} from './api'

/**
 * Разбор пачки бумажных работ: от PDF до оценок.
 *
 * Четыре шага, и порядок у них не случайный — он повторяет то, как эту работу
 * делают руками: сперва положили пачку в сканер, потом разложили по именам,
 * потом проверили спорное, потом выставили баллы.
 *
 *   1. **файл** — выбрали PDF;
 *   2. **чтение** — браузер рисует страницы, вырезает шапки и шлёт их на
 *      чтение по одной. Прогресс настоящий, а не «идёт загрузка»;
 *   3. **сомнения** — обязательный шаг: всё, в чём система не уверена,
 *      человек решает сам. Пропустить его нельзя, и это главное правило всего
 *      экрана: чужая контрольная, приписанная однокласснику, дороже любой
 *      экономии на вопросах;
 *   4. **проверка** — необязательный: пройти глазами всё, включая то, в чём
 *      система уверена. Пропускается кнопкой «доверяю».
 *
 * Страницы не хранятся на сервере, а прочитанное хранится: чтение стоит денег,
 * и закрытая вкладка не должна стоить их второй раз.
 */
export default function ScanWizard({ work, onClose, onDone }) {
  const { t } = useTranslation()

  const [stage, setStage] = useState('loading')
  const [scale, setScale] = useState([])
  const [file, setFile] = useState(null)
  const [pages, setPages] = useState([])
  const [state, setState] = useState(null)
  const [done, setDone] = useState(0)
  const [total, setTotal] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const stop = useRef(false)

  useEffect(() => () => { stop.current = true }, [])

  /* Шкала — это и есть «сколько было задач и по сколько баллов». Спрашиваем
     её первой и только если её ещё нет: у работы, которую уже настроили,
     второй раз спрашивать незачем. */
  useEffect(() => {
    let alive = true
    Promise.all([fetchScale(work.id), fetchScanState(work.id)])
      .then(([answer, known]) => {
        if (!alive) return
        setScale(answer.criteria ?? [])
        setState(known)
        setStage((answer.criteria ?? []).length ? 'file' : 'questions')
      })
      .catch((problem) => alive && setError(problem.message))
    return () => { alive = false }
  }, [work.id])

  const run = async (task) => {
    setBusy(true)
    setError(null)
    try {
      return await task()
    } catch (problem) {
      setError(problem.message)
      return null
    } finally {
      setBusy(false)
    }
  }

  const start = async (chosen) => {
    if (!chosen) return
    setFile(chosen)
    setStage('reading')
    setError(null)
    stop.current = false

    // модуль обработки грузится лениво: pdfjs большой, а нужен он тут одному
    // экрану из всего приложения
    const { walk } = await import('./scanBatch')
    // список живёт снаружи try: в обработчике ошибки состояние компонента ещё
    // старое, и по нему выходило бы «не прочитано ничего» даже после двадцати
    // страниц
    const seen = []

    try {
      /* Пачка НЕ сбрасывается автоматически, и это про деньги. Чтение платное,
         а сорваться оно может на середине — кончился потолок, отвалилась сеть.
         Сброс перед началом стёр бы всё уже оплаченное, и повтор стоил бы
         второй раз. Без него повтор бесплатен: у страницы есть отпечаток, и
         сервер отдаёт прочитанное, не спрашивая модель. Начать по-настоящему
         заново — отдельная кнопка, потому что это разрушительное действие. */
      const collected = await walk(chosen, {
        stop: () => stop.current,
        onPage: (page, count) => {
          seen.push(page)
          setPages([...seen])
          setDone(seen.length)
          setTotal(count)
        },
        send: async ({ index, blob, mark }) => {
          const answer = await readScanPage(work.id, { index, blob, mark })
          setState(answer)
          return true
        },
        blank: async (index) => setState(await markHeaderless(work.id, index)),
      })
      setPages(collected)
      setState(await fetchScanState(work.id))
      setStage('doubts')
    } catch (problem) {
      // прочитанное до сбоя остаётся: за него уже заплачено, и разложить
      // остальное руками лучше, чем начинать пачку сначала
      setError(problem.message)
      setState(await fetchScanState(work.id).catch(() => null))
      setStage(seen.length ? 'doubts' : 'file')
    }
  }

  const decide = async (index, student) =>
    run(async () => setState(await editScanPage(work.id, { index, student })))

  const fix = async (index, cells) =>
    run(async () => setState(await editScanPage(work.id, { index, cells })))

  const finish = async () =>
    run(async () => {
      const result = await applyScan(work.id, file)
      onDone?.(result)
      onClose()
    })

  const packets = state?.packets ?? []
  const doubts = packets.filter((packet) => packet.trouble.length)
  const byIndex = Object.fromEntries(pages.map((page) => [page.index, page]))
  const nameOf = (id) =>
    state?.students.find((one) => one.id === id)?.name ?? t('scan.nobody')
  const readOf = (index) => state?.pages?.find((page) => page.index === index)

  return (
    <Modal onClose={onClose} title={t('scan.title', { name: work.title })}>
      {error && <p className="error">{error}</p>}

      {stage === 'loading' && <p className="hint">{t('common.loading')}</p>}

      {stage === 'questions' && (
        <QuestionsStep
          busy={busy}
          onSave={(criteria) =>
            run(async () => {
              const answer = await saveScale(work.id, criteria)
              setScale(answer.criteria ?? criteria)
              setStage('file')
            })
          }
        />
      )}

      {stage === 'file' && (
        <FileStep
          onPick={start}
          busy={busy}
          questions={scale.length}
          read={state?.pages?.length ?? 0}
          onReset={() => run(async () => setState(await resetScan(work.id)))}
        />
      )}

      {stage === 'reading' && (
        <section className="scan-progress">
          <p>{t('scan.reading', { done, total: total || '…' })}</p>
          <progress value={done} max={total || 1} />
          <p className="hint">{t('scan.readingHint')}</p>
          {state?.budget && (
            <p className="hint">
              {t('scan.spent', {
                spent: `$${(state.budget.spent_micros / 1e6).toFixed(2)}`,
                limit: `$${(state.budget.limit_micros / 1e6).toFixed(2)}`,
              })}
            </p>
          )}
          <button type="button" className="secondary" onClick={() => { stop.current = true }}>
            {t('scan.stop')}
          </button>
        </section>
      )}

      {stage === 'doubts' && state && (
        <DoubtStep
          doubts={doubts}
          conditions={state.conditions}
          packets={packets.length}
          pages={byIndex}
          readOf={readOf}
          students={state.students}
          nameOf={nameOf}
          busy={busy}
          onDecide={decide}
          onNext={() => setStage('check')}
        />
      )}

      {stage === 'check' && state && (
        <CheckStep
          state={state}
          pages={byIndex}
          busy={busy}
          onFix={fix}
          onBack={() => setStage('doubts')}
          onApply={finish}
        />
      )}
    </Modal>
  )
}

/**
 * Сколько было задач и по сколько баллов.
 *
 * Клеток на бланке всегда пятнадцать, а задач бывает меньше — и тогда лишние
 * клетки обязаны остаться пустыми. Это не формальность: балл, прочитанный в
 * клетке, которой у работы нет, ловит сдвиг на клетку, то есть самую опасную
 * ошибку чтения.
 *
 * Максимум спрашивается один на всех, а правится по одной: у большинства работ
 * он одинаковый, а вводить пятнадцать одинаковых чисел — наказание.
 */
function QuestionsStep({ onSave, busy }) {
  const { t } = useTranslation()
  const [count, setCount] = useState(15)
  const [max, setMax] = useState(3)
  const [each, setEach] = useState(null)

  const numbers = Array.from({ length: count }, (_, i) => i + 1)
  const maxOf = (number) => each?.[number] ?? max

  return (
    <section>
      <p className="hint">{t('scan.questionsHint')}</p>
      <div className="row">
        <label className="field">
          <span>{t('scan.questionCount')}</span>
          <input
            type="number"
            min="1"
            max="15"
            value={count}
            disabled={busy}
            onChange={(event) => setCount(Math.min(15, Math.max(1, Number(event.target.value) || 1)))}
          />
        </label>
        <label className="field">
          <span>{t('scan.maxMark')}</span>
          <input
            type="number"
            min="1"
            max="99"
            value={max}
            disabled={busy}
            onChange={(event) => setMax(Math.max(1, Number(event.target.value) || 1))}
          />
        </label>
      </div>

      <details>
        <summary>{t('scan.perQuestion')}</summary>
        <div className="row">
          {numbers.map((number) => (
            <label key={number} className="scan-cell">
              <span>Q{number}</span>
              <input
                type="number"
                min="1"
                max="99"
                value={maxOf(number)}
                disabled={busy}
                onChange={(event) =>
                  setEach({ ...(each ?? {}), [number]: Math.max(1, Number(event.target.value) || 1) })
                }
              />
            </label>
          ))}
        </div>
      </details>

      <div className="actions">
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            onSave(numbers.map((number) => ({ name: `Q${number}`, maximum: maxOf(number) })))
          }
        >
          {t('common.save')}
        </button>
      </div>
    </section>
  )
}

/** Шаг: выбрать файл. Всегда PDF — так его отдаёт и сканер, и телефон. */
function FileStep({ onPick, busy, questions, read, onReset }) {
  const { t } = useTranslation()
  const [over, setOver] = useState(false)

  return (
    <section>
      <p className="hint">{t('scan.pickHint')}</p>
      {questions > 0 && (
        <p className="hint">{t('scan.questionsSet', { count: questions })}</p>
      )}

      {/* бланк печатают раз в год пачкой, но взять его должно быть откуда */}
      <p className="hint">
        <a href="/blank.pdf" target="_blank" rel="noreferrer">
          {t('scan.printBlank')}
        </a>
      </p>

      {read > 0 && (
        <p className="hint">
          {t('scan.alreadyRead', { count: read })}{' '}
          <button type="button" className="link" disabled={busy} onClick={onReset}>
            {t('scan.startOver')}
          </button>
        </p>
      )}
      <label
        className={over ? 'dropzone over' : 'dropzone'}
        onDragOver={(event) => { event.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          onPick(event.dataTransfer.files[0])
        }}
      >
        <input
          type="file"
          accept="application/pdf"
          disabled={busy}
          onChange={(event) => onPick(event.target.files[0])}
        />
        <span>{t('scan.pick')}</span>
      </label>
    </section>
  )
}

/**
 * Шаг сомнений: всё, в чём система не уверена.
 *
 * Показывается **всегда**, даже когда сомнений нет: пустой шаг говорит
 * «сомнений нет» и это тоже ответ. Пропустить его нельзя, пока хоть у одной
 * страницы нет владельца.
 */
function DoubtStep({
  doubts,
  conditions,
  packets,
  pages,
  readOf,
  students,
  nameOf,
  busy,
  onDecide,
  onNext,
}) {
  const { t } = useTranslation()
  const stuck = doubts.filter((packet) => packet.trouble.includes('no_owner'))

  return (
    <section className="scan-doubts">
      {/* сколько листов условий нашлось — по ним и разрезана пачка */}
      {conditions > 0 && (
        <p className="hint">{t('scan.conditions', { count: conditions, packets })}</p>
      )}

      {doubts.length === 0 ? (
        <p className="hint">{t('scan.noDoubts')}</p>
      ) : (
        <ul className="scan-cards">
          {doubts.map((packet) => {
            const first = readOf(packet.pages[0])
            return (
              <li key={packet.number} className="panel">
                <p className="hint">
                  {t('scan.packetPages', {
                    list: packet.pages.map((index) => index + 1).join(', '),
                  })}{' '}
                  · {packet.trouble.map((code) => t(`scan.trouble.${code}`)).join(' · ')}
                </p>

                {/* полоски всех листов пакета: чьи они, видно по любой из них */}
                {packet.pages.slice(0, 3).map(
                  (index) =>
                    pages[index]?.strip && (
                      <img key={index} className="scan-strip" src={pages[index].strip} alt="" />
                    ),
                )}

                <p className="hint">
                  {t('scan.readAs', {
                    name: `${first?.first_name ?? ''} ${first?.surname ?? ''}`.trim() || '—',
                  })}
                  {packet.student ? ` → ${nameOf(packet.student)}` : ''}
                </p>

                <div className="row">
                  {(packet.candidates.length
                    ? packet.candidates
                    : students.map((one) => one.id)
                  )
                    .slice(0, 6)
                    .map((id) => (
                      <button
                        key={id}
                        type="button"
                        className="secondary compact"
                        disabled={busy}
                        onClick={() => onDecide(packet.pages[0], id)}
                      >
                        {nameOf(id)}
                      </button>
                    ))}
                  <button
                    type="button"
                    className="link"
                    disabled={busy}
                    onClick={() => onDecide(packet.pages[0], null)}
                  >
                    {t('scan.nobody')}
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <div className="actions">
        <button type="button" disabled={busy || stuck.length > 0} onClick={onNext}>
          {t('scan.toCheck')}
        </button>
        {stuck.length > 0 && (
          <span className="hint">{t('scan.stillStuck', { count: stuck.length })}</span>
        )}
      </div>
    </section>
  )
}

/**
 * Шаг проверки: ученики и их баллы.
 *
 * Пропускается целиком — «доверяю». Это не небрежность: сомнительное уже
 * разобрано шагом раньше, а здесь остаётся то, в чём система уверена, и
 * заставлять смотреть на тридцать уверенных строк значит превращать проверку
 * в ритуал. Но возможность посмотреть есть, и цифры правятся на месте.
 */
function CheckStep({ state, pages, busy, onFix, onBack, onApply }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(null)
  const questions = Array.from({ length: state.questions }, (_, i) => i + 1)

  const cellsOf = (index) => state.pages.find((page) => page.index === index)?.cells ?? []

  return (
    <section className="scan-check">
      <p className="hint">{t('scan.checkHint')}</p>

      <div className="scan-table-wrap">
        <table className="scan-table">
          <thead>
            <tr>
              <th>{t('scan.student')}</th>
              <th>{t('scan.pagesColumn')}</th>
              {questions.map((number) => (
                <th key={number}>Q{number}</th>
              ))}
              <th>{t('scan.total')}</th>
            </tr>
          </thead>
          <tbody>
            {state.students.map((student) => (
              <tr key={student.id} className={student.pages.length ? '' : 'empty'}>
                <td>{student.name}</td>
                <td className="hint">
                  {student.pages.length
                    ? student.pages.map((index) => (
                        <button
                          key={index}
                          type="button"
                          className="link"
                          onClick={() => setOpen(open === index ? null : index)}
                        >
                          {index + 1}
                        </button>
                      ))
                    : '—'}
                </td>
                {questions.map((number) => (
                  <td key={number}>{student.marks[number] ?? ''}</td>
                ))}
                <td>
                  <b>{student.total}</b>
                  {student.conflicts.length > 0 && (
                    <span className="hint warning">
                      {' '}
                      {t('scan.conflict', { list: student.conflicts.join(', ') })}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open !== null && (
        <div className="panel">
          <p className="hint">{t('scan.pageNumber', { number: open + 1 })}</p>
          {pages[open]?.strip && <img className="scan-strip" src={pages[open].strip} alt="" />}
          <div className="row">
            {questions.map((number) => (
              <label key={number} className="scan-cell">
                <span>Q{number}</span>
                <input
                  type="number"
                  min="0"
                  max="99"
                  value={cellsOf(open)[number - 1] ?? ''}
                  disabled={busy}
                  onChange={(event) => {
                    const cells = [...cellsOf(open)]
                    cells[number - 1] =
                      event.target.value === '' ? null : Number(event.target.value)
                    onFix(open, cells)
                  }}
                />
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="actions">
        <button type="button" disabled={busy} onClick={onApply}>
          {t('scan.apply')}
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={onBack}>
          {t('common.back')}
        </button>
      </div>
    </section>
  )
}
