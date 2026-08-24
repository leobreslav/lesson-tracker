import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import {
  applyScan,
  editScanPage,
  fetchQuestions,
  fetchScanState,
  markHeaderless,
  readScanPage,
  readScanQuestions,
  resetScan,
  saveQuestions,
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
 *   3. **разбор** — обязательный шаг: весь файл, страница за страницей, и
 *      всё, в чём система не уверена, человек решает сам. Пропустить его
 *      нельзя, пока хоть у одной страницы нет хозяина, и это главное правило
 *      всего экрана: чужая контрольная, приписанная однокласснику, дороже
 *      любой экономии на вопросах;
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
  const [readQuestions, setReadQuestions] = useState(false)
  const [questions, setQuestions] = useState(null)
  const stop = useRef(false)

  useEffect(() => () => { stop.current = true }, [])

  /* Шкала — это и есть «сколько было задач и по сколько баллов». Спрашиваем
     её первой и только если её ещё нет: у работы, которую уже настроили,
     второй раз спрашивать незачем. */
  useEffect(() => {
    let alive = true
    Promise.all([fetchQuestions(work.id), fetchScanState(work.id)])
      .then(([answer, known]) => {
        if (!alive) return
        setScale(answer.questions ?? [])
        setState(known)
        // шкалу подтверждают перед каждым чтением: узнать, что она не та,
        // можно было только после того, как за пачку уже заплачено
        setStage('questions')
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

  const start = async (chosen, alsoQuestions) => {
    if (!chosen) return
    setFile(chosen)
    setQuestions(null)
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
        blank: async (index, ours) =>
          setState(await markHeaderless(work.id, index, ours)),
        questions: alsoQuestions
          ? async (sheet) => {
              const answer = await readScanQuestions(work.id, sheet)
              setQuestions((was) => ({
                found: (was?.found ?? 0) + answer.found,
                written: (was?.written ?? 0) + answer.written,
                extra: [...(was?.extra ?? []), ...answer.extra],
                marks_differ: [...(was?.marks_differ ?? []), ...answer.marks_differ],
              }))
              return answer
            }
          : null,
      })
      setPages(collected)
      setState(await fetchScanState(work.id))
      setStage('pages')
    } catch (problem) {
      // прочитанное до сбоя остаётся: за него уже заплачено, и разложить
      // остальное руками лучше, чем начинать пачку сначала
      setError(problem.message)
      setState(await fetchScanState(work.id).catch(() => null))
      setStage(seen.length ? 'pages' : 'file')
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

  const byIndex = Object.fromEntries(pages.map((page) => [page.index, page]))

  return (
    <Modal onClose={onClose} title={t('scan.title', { name: work.title })}>
      {error && <p className="error">{error}</p>}

      {stage === 'loading' && <p className="hint">{t('common.loading')}</p>}

      {stage === 'questions' && (
        <QuestionsStep
          busy={busy}
          scale={scale}
          onSave={(questions) =>
            run(async () => {
              const answer = await saveQuestions(work.id, questions)
              setScale(answer.questions ?? questions)
              setStage('file')
            })
          }
        />
      )}

      {stage === 'file' && (
        <FileStep
          onPick={(chosen) => start(chosen, readQuestions)}
          busy={busy}
          readQuestions={readQuestions}
          onReadQuestions={setReadQuestions}
          questions={scale.length}
          read={state?.pages?.length ?? 0}
          onReset={() => run(async () => setState(await resetScan(work.id)))}
        />
      )}

      {stage === 'reading' && (
        <section className="scan-step scan-progress">
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

      {stage === 'pages' && state && (
        <PagesStep
          state={state}
          all={pages}
          byIndex={byIndex}
          questions={questions}
          busy={busy}
          onDecide={decide}
          onFix={fix}
          onNext={() => setStage('check')}
        />
      )}

      {stage === 'check' && state && (
        <CheckStep
          state={state}
          pages={byIndex}
          busy={busy}
          onFix={fix}
          onBack={() => setStage('pages')}
          onApply={finish}
        />
      )}
    </Modal>
  )
}

/**
 * Сколько было задач и по сколько баллов.
 *
 * Заводятся именно **вопросы работы**, а не критерии оценивания: балл за
 * задачу и уровень по критерию — разные оси. Критерии (A, B, C, D в MYP)
 * отвечают на «как работа оценена», и задачами не являются.
 *
 * Клеток на бланке всегда пятнадцать, а задач бывает меньше — и тогда лишние
 * клетки обязаны остаться пустыми. Это не формальность: балл, прочитанный в
 * клетке, которой у работы нет, ловит сдвиг на клетку, то есть самую опасную
 * ошибку чтения.
 *
 * Максимум спрашивается один на всех, а правится по одной: у большинства работ
 * он одинаковый, а вводить пятнадцать одинаковых чисел — наказание.
 */
function QuestionsStep({ onSave, busy, scale = [] }) {
  const { t } = useTranslation()

  /* Шкала спрашивается **перед каждым чтением**, а не только у ненастроенной
     работы, и вводится она не заново: нынешняя подставлена, и шаг читается как
     «проверьте, прежде чем платить». Причина в цене ошибки. По шкале
     раскладываются баллы и ловится сдвиг на клетку («балл в клетке, которой у
     работы нет»), а узнать, что шкала не та, можно было только после
     чтения — то есть уже заплатив за всю пачку. У живой работы стояло «4
     задачи по 1 баллу», тогда как на листах их было пятнадцать, а баллы
     доходили до трёх: каждая страница честно ругалась, и ни одна из ругани не
     была про настоящую ошибку. */
  const known = scale.length
  const [count, setCount] = useState(() => (known ? scale.length : 15))
  const [max, setMax] = useState(() =>
    known ? Math.max(...scale.map((one) => one.maximum || 1)) : 3,
  )
  const [each, setEach] = useState(() =>
    known && new Set(scale.map((one) => one.maximum)).size > 1
      ? Object.fromEntries(scale.map((one, i) => [i + 1, one.maximum]))
      : null,
  )
  // как вопросы зовутся: «1а», «324 из Галицкого». Пусто — зовутся номерами
  const [names, setNames] = useState(() =>
    Object.fromEntries(scale.map((one, i) => [i + 1, one.label ?? ''])),
  )

  const numbers = Array.from({ length: count }, (_, i) => i + 1)
  const maxOf = (number) => each?.[number] ?? max
  const nameOf = (number) => names[number] ?? ''

  return (
    <section className="scan-step">
      <p className="hint">{known ? t('scan.checkScale') : t('scan.questionsHint')}</p>
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

      {/* по одному: имя и цена. Имя тут, а не только в окне задачи, потому
          что бумажную работу заводят именно здесь и целиком — пятнадцать
          ячеек сразу; переименовывать их потом по одной, открывая пятнадцать
          окон, значило бы не дать этой возможности вовсе */}
      <details>
        <summary>{t('scan.perQuestion')}</summary>
        <p className="hint">{t('scan.perQuestionHint')}</p>
        <div className="row">
          {numbers.map((number) => (
            <div key={number} className="scan-cell">
              <input
                className="scan-cell-name"
                maxLength={16}
                placeholder={String(number)}
                value={nameOf(number)}
                disabled={busy}
                aria-label={t('scan.questionName', { number })}
                onChange={(event) =>
                  setNames({ ...names, [number]: event.target.value })
                }
              />
              <input
                type="number"
                min="1"
                max="99"
                value={maxOf(number)}
                disabled={busy}
                aria-label={t('scan.questionMax', { number })}
                onChange={(event) =>
                  setEach({ ...(each ?? {}), [number]: Math.max(1, Number(event.target.value) || 1) })
                }
              />
            </div>
          ))}
        </div>
      </details>

      <div className="actions">
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            onSave(
              numbers.map((number) => ({
                label: nameOf(number).trim(),
                maximum: maxOf(number),
              })),
            )
          }
        >
          {t('common.save')}
        </button>
      </div>
    </section>
  )
}

/** Шаг: выбрать файл. Всегда PDF — так его отдаёт и сканер, и телефон. */
function FileStep({ onPick, busy, questions, read, onReset, readQuestions, onReadQuestions }) {
  const { t } = useTranslation()
  const [over, setOver] = useState(false)

  return (
    <section className="scan-step">
      <p className="hint">{t('scan.pickHint')}</p>
      {questions > 0 && (
        <p className="hint">{t('scan.questionsSet', { count: questions })}</p>
      )}

      {/* Ссылки на бланк тут нет намеренно: печатают его до контрольной, а
          мастер открывают после, со стопкой исписанных листов в руках.
          Живёт она теперь на самой странице работ — см. `Works.jsx` */}

      {/* Как сложена пачка — главное, что человек должен знать до нажатия:
          переделывать после чтения дорого, оно платное. Раскрыто, а не в
          «подробностях»: первый раз это читают все, а второй раз читать
          необязательно — глаз проскочит три коротких блока быстрее, чем
          рука откроет каретку */}
      <div className="scan-about">
        <p className="hint">
          <b>{t('scan.about.pileTitle')}</b>
        </p>
        <ul className="hint">
          <li>{t('scan.about.pileOrder')}</li>
          <li>{t('scan.about.pileSheets')}</li>
          <li>{t('scan.about.pileConditions')}</li>
        </ul>

        <p className="hint">
          <b>{t('scan.about.limitsTitle')}</b>
        </p>
        <ul className="hint">
          <li>{t('scan.about.limitsOneWork')}</li>
          <li>{t('scan.about.limitsHeader')}</li>
          <li>{t('scan.about.limitsCells')}</li>
        </ul>

        <p className="hint">
          <b>{t('scan.about.afterTitle')}</b>
        </p>
        <ul className="hint">
          <li>{t('scan.about.afterStrip')}</li>
          <li>{t('scan.about.afterSplit')}</li>
          <li>{t('scan.about.afterMarks')}</li>
          <li>{t('scan.about.afterSource')}</li>
        </ul>
      </div>

      {/* условия читаются по просьбе: страница целиком дороже полоски шапки,
          а нужна она один раз на пачку */}
      {questions > 0 && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={readQuestions}
            disabled={busy}
            onChange={(event) => onReadQuestions(event.target.checked)}
          />
          {t('scan.readQuestions')}
        </label>
      )}
      {readQuestions && <p className="hint">{t('scan.readQuestionsHint')}</p>}

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
        {/* поле спрятано, а не убрано: нажатие по зоне доходит до него
            через саму подпись, и выбор файла работает как прежде.

            Видимым оно стояло, и рядом с зоной сброса браузер рисовал свою
            кнопку — «Choose File» по-английски при любом языке интерфейса
            (подпись у неё от браузера, и `t()` до неё не дотягивается) и
            своей рамкой мимо всех прочих. Заодно она и заслоняла
            перетаскивание: зона под ней читалась подписью к кнопке, а не
            местом, куда можно бросить. */}
        <input
          type="file"
          accept="application/pdf"
          hidden
          disabled={busy}
          onChange={(event) => onPick(event.target.files[0])}
        />
        <span>{t('scan.pick')}</span>
      </label>
    </section>
  )
}

/**
 * Шаг разбора: весь файл, страница за страницей.
 *
 * Единицей показа был **пакет** — работа одного ученика целиком, — и на живой
 * пачке это оказалось не тем, о чём стоит спрашивать. Пакет собирает
 * раскладка, а раскладка ошибается: в одну карточку попадали листы двух
 * разных учеников, подписанные разными именами, и у вопроса «чей это пакет»
 * правильного ответа не было вовсе. Спрашивать надо о том, в чём система
 * может ошибиться, а ошибается она в **странице**.
 *
 * Показываются все страницы файла, а не только спорные. Спорные помечены и по
 * ним ходит отдельная кнопка — иначе на пачке в тридцать листов их искали бы
 * перелистыванием, — но посмотреть глазами можно любую: уверенное чтение тоже
 * бывает неверным, и ловится это только так. Два таких случая на живой пачке
 * пометками не поймались вовсе: «Denis», прочитанный как «Misha», и «LAPE»,
 * ставшее «LAPA» при двух похожих фамилиях в классе.
 *
 * И показывается **вся страница**, а не полоска шапки. Полоска — это то, что
 * уехало на чтение; человек же проверяет не чтение, а работу, и чей это лист,
 * видно по почерку в поле записи не хуже, чем по подписи.
 */
function PagesStep({ state, all, byIndex, questions, busy, onDecide, onFix, onNext }) {
  const { t } = useTranslation()
  const [at, setAt] = useState(0)
  /* Увеличение листа. Превью — это страница A4 в колонку шириной с пол-окна,
     и на ней не всегда видно, «Денис» там написано или «Миша», а решать надо
     именно это. Держится между страницами: разглядывают обычно подряд. */
  const [zoom, setZoom] = useState(1)
  const sheet = useRef(null)

  const STEPS = [1, 1.5, 2, 3, 4]
  const zoomBy = (step) => {
    const now = STEPS.indexOf(zoom)
    setZoom(STEPS[Math.min(STEPS.length - 1, Math.max(0, now + step))])
  }

  /* Щелчок по листу увеличивает **в это место**, а не в середину: тычут туда,
     что хотят разглядеть, и приехать после этого в центр страницы значит
     заставить искать заново. */
  const zoomAt = (event) => {
    const box = sheet.current
    const rect = event.currentTarget.getBoundingClientRect()
    const fx = (event.clientX - rect.left) / rect.width
    const fy = (event.clientY - rect.top) / rect.height
    const next = zoom > 1 ? 1 : 2
    setZoom(next)
    if (!box || next === 1) return
    requestAnimationFrame(() => {
      box.scrollLeft = fx * box.scrollWidth - box.clientWidth / 2
      box.scrollTop = fy * box.scrollHeight - box.clientHeight / 2
    })
  }

  const students = state.students ?? []
  const nameOf = (id) => students.find((one) => one.id === id)?.name ?? t('scan.nobody')
  const rowOf = (index) => state.pages?.find((page) => page.index === index)

  // Показываем то, что нарисовал браузер: страницы файла, все до одной. Список
  // сервера короче — в нём только прочитанное, — и по нему лист, до которого
  // чтение не дошло, просто не существовал бы.
  const sheets = all.length ? all : (state.pages ?? []).map((page) => ({ index: page.index }))
  const here = sheets[Math.min(at, sheets.length - 1)]
  const row = here ? rowOf(here.index) : null

  const troubled = (page) => (rowOf(page.index)?.trouble ?? []).length > 0
  const stuck = sheets.filter((page) => (rowOf(page.index)?.trouble ?? []).includes('no_owner'))

  /* Прыжок по спорным. Перелистывать тридцать листов ради четырёх — это и
     есть та работа, ради избавления от которой пачку разбирает машина. */
  const jump = (step) => {
    for (let i = 1; i <= sheets.length; i += 1) {
      const next = (at + step * i + sheets.length * i) % sheets.length
      if (troubled(sheets[next])) return setAt(next)
    }
  }

  /*
   * Какие клетки показать. Шкала работы — обязательно, а за ней ещё всякая
   * клетка, в которой что-то прочитано.
   *
   * Показывались только клетки шкалы, и это было хуже, чем кажется. У работы
   * с четырьмя задачами прочитанные Q5 и Q8 не показывались **нигде**: экран
   * писал «балл в клетке, которой у работы нет», но какая это клетка и что в
   * ней стоит, узнать было негде, а стереть случайную галочку — тем более.
   * Пометка без предмета не проверяется и не чинится.
   */
  const cells = row?.cells ?? []
  const columns = Array.from({ length: 15 }, (_, i) => i).filter(
    (position) => position < state.questions || cells[position] != null,
  )
  const nameOfQuestion = (number) => state.question_names?.[number - 1] ?? String(number)

  const setCell = (position, value) => {
    const next = [...(row?.cells ?? Array(16).fill(null))]
    next[position] = value === '' ? null : Number(value)
    onFix(here.index, next)
  }

  return (
    <section className="scan-step scan-review">
      <SpendLine spend={state.spend} />

      {/* сколько листов условий нашлось — по ним и разрезана пачка */}
      {state.conditions > 0 && (
        <p className="hint">
          {t('scan.conditions', { count: state.conditions, packets: state.packets?.length ?? 0 })}
        </p>
      )}

      {questions && (
        <p className="hint">
          {t('scan.questionsRead', { count: questions.written, found: questions.found })}
          {questions.extra.length > 0 && ` · ${t('scan.questionsExtra', { list: questions.extra.join(', ') })}`}
          {questions.marks_differ.length > 0 &&
            ` · ${t('scan.questionsMarks', { list: questions.marks_differ.map((one) => `Q${one.number}=${one.marks}`).join(', ') })}`}
        </p>
      )}

      {/* лента страниц: где мы и что где лежит, одним взглядом */}
      <ol className="scan-film">
        {sheets.map((page, position) => {
          const its = rowOf(page.index)
          const mark = its?.headerless
            ? 'conditions'
            : (its?.trouble ?? []).includes('no_owner')
              ? 'stuck'
              : troubled(page)
                ? 'doubt'
                : its?.student
                  ? 'settled'
                  : ''
          return (
            <li key={page.index}>
              <button
                type="button"
                className={`scan-film-page ${mark} ${position === at ? 'here' : ''}`}
                onClick={() => setAt(position)}
              >
                {page.index + 1}
              </button>
            </li>
          )
        })}
      </ol>

      <div className="row middle scan-walk">
        <button
          type="button"
          className="secondary compact"
          disabled={busy || at === 0}
          onClick={() => setAt(at - 1)}
        >
          {t('scan.prev')}
        </button>
        <span>{t('scan.pageOf', { number: (here?.index ?? 0) + 1, count: sheets.length })}</span>
        <button
          type="button"
          className="secondary compact"
          disabled={busy || at >= sheets.length - 1}
          onClick={() => setAt(at + 1)}
        >
          {t('scan.next')}
        </button>
        <button
          type="button"
          className="link"
          disabled={busy || !sheets.some(troubled)}
          onClick={() => jump(1)}
        >
          {t('scan.nextDoubt')}
        </button>

        <button
          type="button"
          className="secondary compact"
          disabled={zoom === STEPS[0]}
          aria-label={t('scan.zoomOut')}
          onClick={() => zoomBy(-1)}
        >
          −
        </button>
        <span className="hint">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="secondary compact"
          disabled={zoom === STEPS[STEPS.length - 1]}
          aria-label={t('scan.zoomIn')}
          onClick={() => zoomBy(1)}
        >
          +
        </button>
      </div>

      <div className="scan-review-body">
        {/* вся страница, а не полоска: чей это лист, видно и по почерку */}
        <div className="scan-sheet" ref={sheet}>
          {byIndex[here?.index]?.preview ? (
            <img
              src={byIndex[here.index].preview}
              alt=""
              style={{ width: `${zoom * 100}%` }}
              className={zoom > 1 ? 'out' : 'in'}
              onClick={zoomAt}
            />
          ) : (
            <p className="hint">{t('scan.noPreview')}</p>
          )}
        </div>

        <div className="scan-side">
          {/* полоска рядом с прочитанным именем: это ровно та картинка, по
              которой модель отвечала, и расхождение видно на ней, а не на
              странице целиком */}
          {byIndex[here?.index]?.strip && (
            <img className="scan-strip" src={byIndex[here.index].strip} alt="" />
          )}

          <p className="hint">
            {t('scan.readAs', {
              name: `${row?.first_name ?? ''} ${row?.surname ?? ''}`.trim() || '—',
            })}
          </p>

          {row?.headerless && (
            <p className="hint">
              {t('scan.headerless')}{' '}
              {/* и почему именно: счёт совпадения с сеткой против порога, плюс
                  нашлась ли метка нашего бланка в углу. Без этих двух чисел
                  «не наш лист» и «плохое фото нашего листа» неразличимы, а это
                  очень разные события */}
              {byIndex[here?.index] &&
                t('scan.headerlessWhy', {
                  score: byIndex[here.index].score,
                  need: byIndex[here.index].need,
                  mark: t(byIndex[here.index].ours ? 'scan.markFound' : 'scan.markMissing'),
                })}
            </p>
          )}

          {(row?.trouble ?? []).length > 0 && (
            <p className="hint warning">
              {row.trouble.map((code) => t(`scan.trouble.${code}`)).join(' · ')}
            </p>
          )}

          <p>
            <b>{row?.student ? nameOf(row.student) : t('scan.nobodyYet')}</b>
            {row?.decided_by_human && <span className="hint"> {t('scan.byHand')}</span>}
          </p>

          {/* тройка лучших — по этой странице, а не по пакету: у пакета
              кандидатов может не быть вовсе, и тогда экран предлагал первых
              по списку класса, то есть заведомо не тех */}
          {(row?.candidates ?? []).length > 0 && (
            <div className="row">
              {row.candidates.map((id) => (
                <button
                  key={id}
                  type="button"
                  className="secondary compact"
                  disabled={busy}
                  onClick={() => onDecide(here.index, id)}
                >
                  {nameOf(id)}
                </button>
              ))}
            </div>
          )}

          {/* ...а список всех — на случай, когда прочиталось не то вовсе.
              Тройка отвечает на «кто из похожих», список — на «а всё-таки» */}
          <div className="row middle">
            <select
              value={row?.student ?? ''}
              disabled={busy}
              onChange={(event) =>
                onDecide(here.index, event.target.value ? Number(event.target.value) : null)
              }
            >
              <option value="">{t('scan.nobody')}</option>
              {students.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
          </div>

          {row && !row.headerless && (
            <div className="row">
              {columns.map((position) => (
                <label
                  key={position}
                  className={`scan-cell ${position >= state.questions ? 'beyond' : ''}`}
                >
                  <span>
                    {position < state.questions
                      ? nameOfQuestion(position + 1)
                      : `Q${position + 1}`}
                  </span>
                  <input
                    type="number"
                    min="0"
                    max="99"
                    value={cells[position] ?? ''}
                    disabled={busy}
                    onChange={(event) => setCell(position, event.target.value)}
                  />
                </label>
              ))}
              <label className="scan-cell">
                <span>{t('scan.pageSum')}</span>
                <input
                  type="number"
                  min="0"
                  max="999"
                  value={cells[15] ?? ''}
                  disabled={busy}
                  onChange={(event) => setCell(15, event.target.value)}
                />
              </label>
            </div>
          )}
        </div>
      </div>

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
 * Во что обошлась эта пачка.
 *
 * Стоит рядом с работой, а не в разделе школы: там отвечают на вопрос
 * администратора «не пора ли поднять потолок», а здесь на вопрос учителя —
 * «во что обошлось вот это чтение». Цена показывается там же, где идёт
 * чтение: узнавать её, уже потратив, — не то же самое, что видеть по ходу.
 */
function SpendLine({ spend }) {
  const { t } = useTranslation()
  if (!spend?.calls) return null

  const money = (micros) => `$${(micros / 1e6).toFixed(3)}`

  return (
    <p className="hint">
      {t('scan.batchSpend', { amount: money(spend.micros), count: spend.calls })}
      {spend.total_micros > spend.micros &&
        ` · ${t('scan.workSpend', { amount: money(spend.total_micros) })}`}
    </p>
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
  // клетка и вопрос связаны местом, а не именем: третья клетка листа — это
  // третий вопрос, как бы учитель его ни назвал. Поэтому имена лежат
  // отдельным списком, а искать по нему надо по номеру клетки
  const nameOfQuestion = (number) =>
    state.question_names?.[number - 1] ?? String(number)

  const cellsOf = (index) => state.pages.find((page) => page.index === index)?.cells ?? []

  return (
    <section className="scan-step scan-check">
      <p className="hint">{t('scan.checkHint')}</p>

      <div className="scan-table-wrap">
        <table className="scan-table">
          <thead>
            <tr>
              <th>{t('scan.student')}</th>
              <th>{t('scan.pagesColumn')}</th>
              {questions.map((number) => (
                <th key={number}>{nameOfQuestion(number)}</th>
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
                  {/* балл, который скан перепишет, называется до записи:
                      прежний мог быть поставлен за онлайн-ответ или прошлым
                      разбором этой же пачки, и молча заменить его нельзя */}
                  {student.overwrites?.length > 0 && (
                    <span className="hint warning">
                      {' '}
                      {t('scan.overwrites', {
                        list: student.overwrites
                          .map((one) =>
                            t('scan.overwrite', {
                              question: one.question,
                              was: one.was,
                              now: one.now,
                            }),
                          )
                          .join(', '),
                      })}
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
          {/* вся страница, а не полоска: проверяют работу, а не чтение */}
          <div className="scan-sheet">
            {pages[open]?.preview && <img src={pages[open].preview} alt="" />}
          </div>
          <div className="row">
            {questions.map((number) => (
              <label key={number} className="scan-cell">
                <span>{nameOfQuestion(number)}</span>
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
