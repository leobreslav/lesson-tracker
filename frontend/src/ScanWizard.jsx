import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
// крошечный модуль с миллиметрами бланка; pdfjs за собой не тянет, в отличие
// от scanSheet.js, который грузится лениво
import { GRID, gridInStrip } from './blankGeometry'
import { dollars } from './money'
import {
  applyScan,
  editScanPage,
  fetchQuestions,
  fetchScanBatch,
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
  /* Звать ли поверх первого читателя Mathpix.
   *
   * Умолчание — «звать», и это не небрежность: ключи в контуре появляются не
   * сами, и раз школа их поставила, второй свидетель нужен. Галочка — способ
   * **отказаться** на конкретной пачке, а не включить: у стопки, где имена
   * вписаны учителем печатными буквами, спорить не о чем, а платить пришлось
   * бы вдвое. */
  const [second, setSecond] = useState(true)
  /* Кем читать имя. Пустая строка — «кем умеете»: контур возьмёт первого
   * доступного сам, и это верное умолчание, потому что порядок предпочтения
   * знает он, а не экран. Человек перебивает его выбором, когда хочет
   * сравнить читателей на своей пачке — единственный способ узнать, кто из
   * них лучше на этом почерке. */
  const [reader, setReader] = useState('')
  const [questions, setQuestions] = useState(null)
  /* Повороты, заданные человеком: страница -> градусы. */
  const [turns, setTurns] = useState({})
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

  const start = async (chosen, alsoQuestions, alsoSecond = true, byReader = '') => {
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
        send: async ({ index, blob, plain, mark }) => {
          const answer = await readScanPage(work.id, {
            index,
            blob,
            plain,
            mark,
            second: alsoSecond,
            reader: byReader,
          })
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

  /*
   * Перевернуть страницу и перечитать её.
   *
   * Скан из автоподатчика приходит вверх ногами не пачкой, а вразнобой: один
   * лист лёг не так. Выправлять его нечем — выпрямление перебирает повороты
   * само, но выбирает по сетке, а сетка симметрична, и на плохом снимке выбор
   * бывает неверным. Тогда человек видит перевёрнутую полоску и до сих пор мог
   * только развести руками.
   *
   * Стоит это **денег**: страница читается заново. Так и должно быть — за
   * перечитывание платят ради верного чтения, а картинка у перевёрнутой другая,
   * и отпечаток другой, поэтому кэш её не отдаст.
   *
   * Без файла поворот невозможен: страницы рисует браузер из PDF, а у
   * вернувшегося к прочитанной пачке его нет.
   */
  const flip = async (index) => {
    if (!file) return
    const turn = ((turns[index] ?? 0) + 180) % 360
    return run(async () => {
      const { openBook, readPage } = await import('./scanBatch')
      const book = await openBook(file)
      const page = await readPage(book, index + 1, {
        turn,
        send: async ({ index: at, blob, plain, mark }) => {
          setState(await readScanPage(work.id, { index: at, blob, plain, mark, second, reader }))
          return true
        },
        blank: async (at, ours) => setState(await markHeaderless(work.id, at, ours)),
      })
      setTurns((was) => ({ ...was, [index]: turn }))
      setPages((was) => was.map((one) => (one.index === index ? page : one)))
      setState(await fetchScanState(work.id))
    })
  }

  const decide = async (index, student) =>
    run(async () => setState(await editScanPage(work.id, { index, student })))

  const fix = async (index, cells) =>
    run(async () => setState(await editScanPage(work.id, { index, cells })))

  /*
   * Записать разобранное можно только вместе с самим PDF.
   *
   * Прочитанное живёт на сервере, а страницы — нет: их режет и раздаёт ученикам
   * та же отправка, которой файл и приезжает. Поэтому вернувшийся к уже
   * прочитанной пачке человек («к страницам» на шаге выбора файла) доходит до
   * конца без файла в руках — и упирался в чужую ошибку DRF: «The submitted
   * data was not a file». Со стороны это не ответ, а поломка.
   *
   * Теперь пустой файл — не отказ, а **просьба**: укажите тот же PDF. Читать
   * его заново не придётся и платить тоже: у каждой страницы есть отпечаток, и
   * сервер отдаёт прочитанное, не спрашивая модель.
   */
  const finish = async (chosen = file) => {
    if (!chosen) return
    return run(async () => {
      const result = await applyScan(work.id, chosen)
      onDone?.(result)

      /* Пачку не удалось сохранить — а применение прошло.
         Закрыть окно молча тут нельзя: снаружи это выглядит как обычный
         успех, и человек узнает о пропаже только тогда, когда придёт
         перезапускать разбор и не найдёт файла. Оценки и работы при этом на
         месте, поэтому это сообщение, а не отказ. */
      if (result.batch_refused) {
        setError(t('scan.batchRefused'))
        setStage('file')
        setState(await fetchScanState(work.id).catch(() => null))
        return
      }

      onClose()
    })
  }

  const byIndex = Object.fromEntries(pages.map((page) => [page.index, page]))

  return (
    <Modal
      onClose={onClose}
      title={t('scan.title', { name: work.title })}
      className="wide"
    >
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

      {/* Просьба прочитать условия снимается вместе с галочкой: галочка могла
          остаться включённой с прошлого открытия, а модели с тех пор не стало —
          и пачка упёрлась бы в отказ на первом же листе условий.

          Читатели приезжают из шага уже разрешёнными: экран показал их
          отмеченными, и уехать на сервер должно ровно показанное. */}
      {stage === 'file' && (
        <FileStep
          onPick={(chosen, byReader, alsoSecond) =>
            start(
              chosen,
              readQuestions && (state?.model_reachable ?? true),
              alsoSecond,
              byReader,
            )
          }
          busy={busy}
          readQuestions={readQuestions}
          onReadQuestions={setReadQuestions}
          secondReader={state?.second_reader ?? { name: 'mathpix', able: false, why: 'not_configured' }}
          modelReachable={state?.model_reachable ?? true}
          readers={state?.readers ?? []}
          reader={reader}
          onReader={setReader}
          second={second}
          onSecond={setSecond}
          questions={scale.length}
          read={state?.pages?.length ?? 0}
          /* Пачки, уже приложенные к работе. Раньше сюда можно было прийти
             только со своим файлом, а он лежит на диске у человека — и через
             неделю после контрольной может там и не лежать. */
          batches={state?.batches ?? []}
          onTake={(batch) => run(() => fetchScanBatch(batch.id, batch.title))}
          onReset={() => run(async () => setState(await resetScan(work.id)))}
          onBack={() => setStage('questions')}
          onForward={() => setStage('pages')}
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
          onFlip={flip}
          canFlip={Boolean(file)}
          onFix={fix}
          onNext={() => setStage('check')}
          onBack={() => setStage('file')}
        />
      )}

      {stage === 'check' && state && (
        <CheckStep
          state={state}
          pages={byIndex}
          busy={busy}
          onFix={fix}
          onBack={() => setStage('pages')}
          hasFile={Boolean(file)}
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
        {/*
          * Одна таблица, а не россыпь квадратиков.
          *
          * Стояли пары полей без подписей: сверху имя с подставленным номером,
          * снизу максимум — две строки цифр одна над другой, и по ним нельзя
          * было сказать, где номер задачи, а где балл. Поэтому шапка называет
          * клетку словом (`Q1`, а не «1»), а строки подписаны слева: колонка
          * читается сверху вниз как «клетка — как зовём — сколько стоит».
          */}
        <div className="scan-table-wrap">
          <div
            className="scan-scale"
            style={{ gridTemplateColumns: `auto repeat(${count}, minmax(0, 1fr))` }}
          >
            <span className="scan-scale-side" />
            {numbers.map((number) => (
              <span key={`head-${number}`} className="scan-scale-head">
                Q{number}
              </span>
            ))}

            <span className="scan-scale-side">{t('scan.rowName')}</span>
            {numbers.map((number) => (
              <input
                key={`name-${number}`}
                maxLength={16}
                placeholder="—"
                value={nameOf(number)}
                disabled={busy}
                aria-label={t('scan.questionName', { number })}
                onChange={(event) =>
                  setNames({ ...names, [number]: event.target.value })
                }
              />
            ))}

            <span className="scan-scale-side">{t('scan.rowMax')}</span>
            {numbers.map((number) => (
              <input
                key={`max-${number}`}
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
            ))}
          </div>
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
function FileStep({
  onPick,
  busy,
  questions,
  read,
  batches = [],
  onTake,
  onReset,
  readQuestions,
  onReadQuestions,
  secondReader,
  modelReachable,
  readers,
  reader,
  onReader,
  second,
  onSecond,
  onBack,
  onForward,
}) {
  const { t } = useTranslation()
  const [over, setOver] = useState(false)

  /* Вопросов человеку два, и оба простые: **кто читает** — модель или
   * Yandex, — и **звать ли поверх него Mathpix**.
   *
   * Было три читателя на двух осях, и человек выбирал отдельно читателя имени
   * и читателя клеток. Развилок от этого стало больше, чем случаев, которые
   * они разбирают: половина ответов отличалась только ценой одного лишнего
   * запроса, а объяснять приходилось и «тот же читатель по имени», и «тот же
   * по вызову». Клетки теперь читает тот же, кто прочитал шапку, и это не
   * упущение, а ответ: у Yandex под клетки своя модель, и зовёт он её сам.
   *
   * Список читателей приезжает с сервера **целиком**: и те, кого можно
   * позвать, и те, кого нельзя, со словом о причине. Показываются тоже
   * целиком, а недоступный — заглушённым. Пропадал он раньше вместе с самим
   * вопросом, и контур без ключей выглядел как контур, где такого читателя не
   * бывает вовсе: чинить это настройкой человек не шёл, потому что чинить,
   * судя по экрану, было нечего.
   *
   * Что показано отмеченным, то и уезжает на сервер. Держать выбор человека
   * отдельно от показанного нельзя: читатель, выбранный минуту назад, мог
   * стать недоступным, и тогда экран показывал бы одно, а пачка читалась бы
   * другим. */
  const ableNames = readers.filter((one) => one.able).map((one) => one.name)
  const nameReader = ableNames.includes(reader) ? reader : ''
  const readerUsed = nameReader || ableNames[0] || ''
  const secondUsed = second && secondReader.able

  /*
   * Взять пачку, приложенную к работе, вместо файла с диска.
   *
   * Дальше она идёт той же дорогой, что и выбранная руками: ниже по течению
   * про разницу не знает никто. Развилка ровно одна и она про деньги —
   * **продолжить** или **перечитать**. Прочитанное узнаётся по отпечатку и
   * второй раз не оплачивается, поэтому продолжение бесплатно; сброс стирает
   * оплаченное, и потому спрашивается тем же `window.confirm`, что и «начать
   * пачку заново» рядом.
   */
  const take = async (batch, afresh) => {
    if (afresh && read > 0 && !window.confirm(t('scan.startOverConfirm', { count: read })))
      return
    const chosen = await onTake(batch)
    if (!chosen) return
    if (afresh && read > 0) await onReset()
    onPick(chosen, readerUsed, secondUsed)
  }

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

      {/*
        * До модели не достучаться — значит роли поменялись, и сказать об этом
        * надо здесь, до нажатия: дальше человек увидит только результат, а по
        * нему «читал не тот» не отличить от «почерк плохой».
        *
        * Две разные беды и две разные фразы. Распознаватель есть — пачка
        * прочитается, просто хуже и без страховки; распознавателя нет —
        * читать нечем вовсе, и узнать это лучше сейчас, чем на тридцатой
        * странице.
        */}
      {/* Предупреждение, а не `.error`: класс ошибки в этом окне занят
          неудавшимся запросом, и второй такой же блок рядом — это два красных
          сообщения об одном и том же, из которых человеку надо выбрать. Здесь
          же не ошибка действия, а состояние контура, известное до нажатия. */}
      {ableNames.length === 0 ? (
        <p className="hint warning">{t('scan.noReader')}</p>
      ) : (
        !modelReachable &&
        !ableNames.includes('anthropic') && (
          <p className="hint warning">
            {t('scan.soleReader', { reader: t(`scan.reader.${readerUsed}`) })}
          </p>
        )
      )}

      {/*
        * Выбор читателя стоит здесь, а не в настройках школы: кто лучше читает
        * **этот** почерк, узнаётся только пачкой, а держит пачку учитель.
        *
        * Радиокнопками, а не списком, и это прямо про заглушённые строки.
        * Недоступный вариант в `select` виден только тому, кто список
        * раскрыл, — то есть тому, кто и так собрался выбирать. Здесь же
        * показать надо ровно **не собравшемуся**: он не знает, что читателей
        * трое, и не узнает, пока строка не попадётся ему на глаза сама.
        */}
      <div className="reader-choice">
        <p className="hint">
          <b>{t('scan.readerLabel')}</b>
        </p>
        {readers.map((one) => (
          <label
            key={one.name}
            className={one.able ? 'checkbox' : 'checkbox off'}
          >
            <input
              type="radio"
              name="name-reader"
              checked={readerUsed === one.name}
              disabled={busy || !one.able}
              onChange={() => onReader(one.name)}
            />
            {t(`scan.reader.${one.name}`)}
            {!one.able && <span className="hint">{t(`scan.why.${one.why}`)}</span>}
          </label>
        ))}
      </div>

      {/* условия читаются по просьбе: страница целиком дороже полоски шапки,
          а нужна она один раз на пачку. Без модели этой просьбы нет: шкалу из
          листа условий собирает она, а распознаватель видит буквы, не задачи */}
      {questions > 0 && modelReachable && (
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

      {/*
        * Второй вопрос, и он один: звать ли поверх первого читателя Mathpix.
        * Решается **до** платежа и на каждой пачке заново — он её удваивает.
        *
        * Подсказка стоит в обоих положениях, а не только во включённом.
        * Снятая галочка тут не «ничего не происходит», а другое поведение:
        * читает один, и ошибётся он молча. Сказать об этом надо ровно в тот
        * момент, когда галочку снимают.
        */}
      <div className="reader-choice">
        <label className={secondReader.able ? 'checkbox' : 'checkbox off'}>
          <input
            type="checkbox"
            checked={secondUsed}
            disabled={busy || !secondReader.able}
            onChange={(event) => onSecond(event.target.checked)}
          />
          {t('scan.secondReader', { reader: t('scan.reader.mathpix') })}
          {!secondReader.able && (
            <span className="hint">{t(`scan.why.${secondReader.why}`)}</span>
          )}
        </label>
        <p className="hint">
          {t(secondUsed ? 'scan.secondReaderOn' : 'scan.secondReaderOff')}
        </p>
      </div>

      {/*
        * Начать пачку заново.
        *
        * Стояла эта кнопка строчной ссылкой в конце серой подсказки, среди
        * четырёх других серых блоков, — и не находилась. А нужна она каждый
        * раз, когда меняется само чтение: прочитанное узнаётся по отпечатку и
        * второй раз не перечитывается, то есть без сброса новое чтение просто
        * не случится.
        *
        * Спрашиваем перед сбросом, и это не ритуал: удаляется **оплаченное**.
        * Тем же `window.confirm`, что и удаление курса или школы.
        */}
      {read > 0 && (
        <div className="row middle">
          {/* Прочитанное никуда не делось, а уйти к нему было нечем: шаг
              выбора файла вёл только вперёд через новый файл, и вернувшийся
              сюда человек оказывался в тупике — пачка разобрана, а показать её
              нельзя. */}
          <button type="button" disabled={busy} onClick={onForward}>
            {t('scan.toPages')}
          </button>
          <button
            type="button"
            className="secondary compact"
            disabled={busy}
            onClick={() => {
              if (window.confirm(t('scan.startOverConfirm', { count: read }))) onReset()
            }}
          >
            {t('scan.startOver')}
          </button>
          <span className="hint">{t('scan.alreadyRead', { count: read })}</span>
        </div>
      )}

      {/*
        * Пачка, уже приложенная к работе.
        *
        * Шаг вёл только через файл с диска, и это был тупик в двух живых
        * случаях сразу: вкладку закрыли на середине разбора (страницы рисует
        * браузер, а файла у новой вкладки нет) и «разобралось не так» через
        * неделю после контрольной, когда скан с диска уже убрали. Теперь
        * пачка остаётся у работы, и оба случая решаются отсюда.
        *
        * Кнопок две, и разница между ними денежная, а не косметическая:
        * продолжение перерисовывает страницы и не платит за прочитанное,
        * перечитывание платит за всю пачку заново.
        */}
      {batches.length > 0 && (
        <div className="scan-about">
          <p className="hint">
            <b>{t('scan.saved.title')}</b>
          </p>
          {batches.map((batch) => (
            <div className="row middle" key={batch.id}>
              <span>{batch.title}</span>
              {read > 0 && (
                <button
                  type="button"
                  className="secondary compact"
                  disabled={busy}
                  onClick={() => take(batch, false)}
                >
                  {t('scan.saved.resume')}
                </button>
              )}
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => take(batch, true)}
              >
                {t('scan.saved.afresh')}
              </button>
            </div>
          ))}
          <p className="hint">
            {t(read > 0 ? 'scan.saved.resumeHint' : 'scan.saved.afreshHint')}
          </p>
        </div>
      )}

      <label
        className={over ? 'dropzone over' : 'dropzone'}
        onDragOver={(event) => { event.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          onPick(event.dataTransfer.files[0], readerUsed, secondUsed)
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
          onChange={(event) => onPick(event.target.files[0], readerUsed, secondUsed)}
        />
        <span>{t('scan.pick')}</span>
      </label>

      {/* Назад — к шкале. Мастер идёт вперёд шагами, и до сих пор единственным
          способом вернуться было закрыть окно и открыть заново; на шаге,
          следующем за платным, это особенно дорого. */}
      <div className="actions">
        <button type="button" className="secondary" disabled={busy} onClick={onBack}>
          {t('scan.back')}
        </button>
      </div>
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
function PagesStep({ state, all, byIndex, questions, busy, canFlip, onDecide, onFlip, onFix, onNext, onBack }) {
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
   * Клеток показывается ровно столько, сколько их на бланке, — все
   * шестнадцать, и всегда.
   *
   * Показывались только клетки шкалы работы, и это было хуже, чем кажется: у
   * работы с четырьмя задачами прочитанные Q5 и Q8 не показывались **нигде**.
   * Экран писал «балл в клетке, которой у работы нет», а какая это клетка и
   * что в ней стоит, узнать было негде — и стереть случайную галочку тоже.
   * Пометка без предмета не проверяется и не чинится.
   *
   * Теперь ряд полей повторяет сетку бланка целиком и стоит под ней колонка в
   * колонку; лишние клетки помечены, но видны и правятся.
   */
  const cells = row?.cells ?? []
  const nameOfQuestion = (number) => state.question_names?.[number - 1] ?? String(number)

  /*
   * Страницу читали двое, и они прочитали разное.
   *
   * Одна модель ошибается **молча**: «Denis» становится «Misha», страница
   * уходит не тому, и выглядит это ровно так же уверенно, как верное чтение.
   * Второй читатель заведён ради этого случая, и весь его смысл доезжает до
   * человека здесь — на странице, где рядом лежат бумага, полоска и обе
   * версии.
   *
   * Показывается спор **предметно**, а не строкой «читатели не сошлись»: та же
   * беда, что была у «балла выше максимума», — пометка без предмета не
   * проверяется и не чинится. Клетка помечена, чужая цифра названа.
   */
  const differs = row?.second?.differs ?? []
  const disputedCells = new Set(
    differs.filter((code) => code.startsWith('cell:')).map((code) => Number(code.slice(5))),
  )
  const labelOfCell = (position) =>
    position === GRID.cells - 1 ? t('scan.pageSum') : `Q${position + 1}`
  const secondSaw = () => {
    const parts = []
    if (differs.includes('name')) {
      // Разбор чужого чтения на графы мог и не сойтись, поэтому у него в
      // запасе строка целиком: показываем прочитанное, а не наш разбор.
      const name = `${row.second.first_name ?? ''} ${row.second.surname ?? ''}`.trim()
      parts.push(name || row.second.text || '—')
    }
    for (const position of disputedCells) {
      parts.push(`${labelOfCell(position)}=${row.second.values?.[position] ?? '—'}`)
    }
    return parts.join(', ')
  }

  /*
   * Балл правится **черновиком**, а уезжает на сервер по уходу из поля.
   *
   * Отправлять на каждое нажатие было ошибкой, и выглядела она хуже, чем
   * была: «не позволяет изменить балл». Поле заблокировано на время запроса
   * (`disabled={busy}`), а чтобы заменить стоящую в клетке цифру, надо сперва
   * её стереть. Стирание уходило запросом, поле гасло — и следующее нажатие
   * попадало в мёртвый контрол. Со стороны это ровно «клетка не даёт себя
   * править», хотя и сервер принимал, и база менялась.
   *
   * Поэтому: пока поле в работе, значение живёт здесь; на сервер оно едет
   * один раз — по `blur` или по Enter. Гасить поле при этом больше незачем.
   */
  const [draft, setDraft] = useState(null)

  const cellValue = (position) =>
    draft && draft.index === here?.index && draft.position === position
      ? draft.value
      : (cells[position] ?? '')

  const commitCell = (position) => {
    if (!draft || draft.index !== here?.index || draft.position !== position) return
    const was = cells[position] ?? ''
    setDraft(null)
    if (String(was) === draft.value) return
    const next = [...(row?.cells ?? Array(16).fill(null))]
    next[position] = draft.value === '' ? null : Number(draft.value)
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

      {/* Ряд условий, лежащий один раз в начале, границ пачке не задаёт —
          делить ему нечего. Зато он общий, и сказать об этом надо здесь, до
          применения: раскладка от этого другая, и работа ученика тоже. */}
      {(state.common_conditions ?? []).length > 0 && (
        <p className="hint">
          {t('scan.commonConditionsLine', {
            count: state.common_conditions.length,
            pages: state.common_conditions.map((index) => index + 1).join(', '),
          })}
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

      {/*
        * Полоска шапки и поля для баллов — один блок, колонка в колонку.
        *
        * Стояли они врозь: полоска в боковой колонке, поля отдельными
        * квадратиками под ней. Сличать в таком виде нечего — глазу приходится
        * считать клетки на картинке и считать квадратики под ней, то есть
        * делать ровно ту работу, на которой сбилась модель. Поставленные под
        * своими клетками поля превращают проверку в один взгляд вдоль строки.
        */}
      {row && (
        <div className="scan-header-block">
          {/* Полоска есть не всегда: у страницы, на которой шапку не нашли,
              выпрямлять было нечего. Клетки при этом остаются — баллы на
              бумаге видно глазами, и вписать их надо уметь. Пока ряд полей
              прятался вместе с полоской, такая страница была тупиком: баллы
              есть, а поставить их некуда.

              Показывается она по **качеству поиска**, а не по признаку «шапки
              нет». Разница не умозрительная: вписанный руками балл снимает
              этот признак — человек сказал, что перед ним лист решения, — и
              страница тут же показывала перекошенную полоску, выпрямленную по
              негодной четвёрке меток. Выглядело это как поломка от нажатия на
              клетку, а на деле было симптомом давнего отказа. */}
          {byIndex[here?.index]?.strip && byIndex[here.index].readable && (
            <img className="scan-strip" src={byIndex[here.index].strip} alt="" />
          )}
          <div
            className="scan-cells"
            style={{
              marginLeft: `${gridInStrip().left * 100}%`,
              width: `${gridInStrip().width * 100}%`,
              gridTemplateColumns: `repeat(${GRID.cells}, minmax(0, 1fr))`,
            }}
          >
            {Array.from({ length: GRID.cells }, (_, position) => (
              <label
                key={position}
                className={[
                  'scan-box',
                  position >= state.questions && position < GRID.cells - 1 ? 'beyond' : '',
                  // «балл выше максимума» — пометка без предмета: сказано, что
                  // такой балл есть, а какой и где, приходилось искать глазами
                  // по шестнадцати клеткам
                  position < state.questions &&
                  state.max_mark &&
                  cells[position] > state.max_mark
                    ? 'too-big'
                    : '',
                  // клетка, о которой читатели не сошлись: смотреть надо
                  // именно на неё, а не на всю строку
                  disputedCells.has(position) ? 'disputed' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <span>
                  {position === GRID.cells - 1 ? t('scan.pageSum') : `Q${position + 1}`}
                </span>
                <input
                  type="number"
                  min="0"
                  max="999"
                  value={cellValue(position)}
                  aria-label={
                    position < state.questions
                      ? nameOfQuestion(position + 1)
                      : `Q${position + 1}`
                  }
                  onChange={(event) =>
                    setDraft({
                      index: here.index,
                      position,
                      value: event.target.value,
                    })
                  }
                  onBlur={() => commitCell(position)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') event.currentTarget.blur()
                  }}
                />
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="scan-review-body">
        {/* Зум стоит **над самой картинкой**, а не в общем ряду наверху.
            Управляет он ею одной, и рука тянется к нему, уже глядя на лист;
            уехав к прочим кнопкам страницы, он оказывался в другом конце
            окна — и связь «эти кнопки про эту картинку» держалась только
            памятью. */}
        <div className="scan-view">
          <div className="row middle scan-zoom">
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
            {/* Поворот стоит здесь же, у картинки: он про неё, и решение о нём
                принимают, глядя на неё. Стоит он денег — страница читается
                заново, — поэтому кнопка обычная, а не незаметная ссылка. */}
            <button
              type="button"
              className="secondary compact"
              disabled={busy || !canFlip}
              title={canFlip ? undefined : t('scan.flipNeedsFile')}
              onClick={() => onFlip(here.index)}
            >
              {t('scan.flip')}
            </button>
          </div>

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
              /* Картинку рисует браузер из PDF. Вернувшийся к уже прочитанной
                 пачке человек файла в руках не держит — и «чтение до неё не
                 дошло» было бы неправдой: чтение дошло, нет картинки. */
              <p className="hint">
                {t(hasFile ? 'scan.noPreview' : 'scan.noPreviewNoFile')}
              </p>
            )}
          </div>
        </div>

        <div className="scan-side">
          {/* Прочерк в «прочитано как» ничего не сообщал: и так видно, что
              шапка пуста. Куда полезнее сказать, откуда взялось предложенное
              имя — из стопки, а не с бумаги. */}
          {`${row?.first_name ?? ''} ${row?.surname ?? ''}`.trim() ? (
            <p className="hint">
              {t('scan.readAs', {
                name: `${row.first_name} ${row.surname}`.trim(),
              })}
            </p>
          ) : (
            <p className="hint">
              {(row?.candidates ?? []).length > 0
                ? t('scan.fromThePile', { name: nameOf(row.candidates[0]) })
                : t('scan.nothingRead')}
            </p>
          )}

          {byIndex[here?.index] && !byIndex[here.index].readable && (
            <p className="hint">
              {row?.headerless ? `${t('scan.headerless')} ` : `${t('scan.noStrip')} `}
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

          {/* что именно увидел второй читатель.
              Третьего чтения тут больше не поминают: спорную страницу
              перечитывал арбитр, а теперь спор решает правило — имя от
              модели, клетки от распознавателя. Что записано, видно в самих
              полях; здесь говорится только о том, что согласия не было. */}
          {differs.length > 0 && (
            <p className="hint warning">
              {t('scan.secondSaw', { reading: secondSaw() })}
            </p>
          )}

          {/*
            * Общие условия — своё состояние, а не «ничья страница».
            *
            * Хозяина у такого листа нет и быть не может: он уедет в начало
            * работы **каждого** ученика. Пока состояния не было, экран
            * показывал здесь имя последнего ученика пачки — того, кому лист
            * положили последним, — и человек шёл исправлять правильное.
            */}
          {row?.common_conditions ? (
            <>
              <p>
                <b>{t('scan.commonConditions')}</b>
              </p>
              <p className="hint">{t('scan.commonConditionsHint')}</p>
            </>
          ) : (
            <p>
              <b>{row?.student ? nameOf(row.student) : t('scan.nobodyYet')}</b>
              {row?.decided_by_human && <span className="hint"> {t('scan.byHand')}</span>}
            </p>
          )}

          {/* тройка лучших — по этой странице, а не по пакету: у пакета
              кандидатов может не быть вовсе, и тогда экран предлагал первых
              по списку класса, то есть заведомо не тех */}
          {(row?.candidates ?? []).length > 0 && (
            <div className="row">
              {/* трое, не больше: кнопок ровно столько, сколько можно окинуть
                  взглядом, а «а всё-таки» отвечает список ниже */}
              {row.candidates.slice(0, 3).map((id) => (
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

          {/* Листание стоит здесь, под выбором хозяина, и это про руку, а не
              про красоту. Работа на этом шаге одна и повторяется тридцать
              четыре раза: посмотреть, назначить, перейти к следующей. Пока
              листание жило наверху, а назначение внизу, каждый круг стоил
              переезда через всё окно — при том что оба действия части одного
              движения. */}
          <div className="row middle scan-walk">
            <button
              type="button"
              className="secondary compact"
              disabled={busy || at === 0}
              onClick={() => setAt(at - 1)}
            >
              {t('scan.prev')}
            </button>
            <span>
              {t('scan.pageOf', { number: (here?.index ?? 0) + 1, count: sheets.length })}
            </span>
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
          </div>
        </div>
      </div>

      {/* Шаг назад слева, шаг вперёд справа — это мастер, а не диалог.
          В диалоге первой стоит главная кнопка, и «отмена» за ней; здесь же
          обе кнопки про движение по шагам, и спорить с тем, куда показывает
          «вперёд», дороже, чем держать единый порядок с диалогами. */}
      <div className="actions">
        <button type="button" className="secondary" disabled={busy} onClick={onBack}>
          {t('scan.back')}
        </button>
        <button type="button" disabled={busy || stuck.length > 0} onClick={onNext}>
          {t('scan.toCheck')}
        </button>
        {/* Сколько страниц без хозяина — знали, а какие именно, приходилось
            искать перелистыванием: на пачке в тридцать четыре листа последняя
            такая страница ищется дольше, чем разбирается. Счётчик поэтому и
            есть кнопка — она ведёт к первой из них. */}
        {stuck.length > 0 && (
          <button
            type="button"
            className="link"
            disabled={busy}
            onClick={() => setAt(sheets.indexOf(stuck[0]))}
          >
            {t('scan.stillStuck', { count: stuck.length })}
          </button>
        )}
      </div>
    </section>
  )
}

/**
 * Порядок поводов — тот, в котором за них платят: сперва обязательное чтение,
 * потом прибавки. Список ведётся здесь, а не берётся из ответа сервера, чтобы
 * разбивка не переставлялась от пачки к пачке: у одной второй читатель был, у
 * другой нет, и алфавит показал бы их в разном порядке.
 *
 * Повод, которого здесь нет, не теряется — он встаёт в конец. Потерянный
 * рубль хуже некрасивого: сумма частей обязана сходиться с целым.
 */
const SPEND_ORDER = [
  'scan_header',
  'scan_second',
  'scan_reread',
  'scan_questions',
]

/**
 * Во что обошлась эта пачка.
 *
 * Стоит рядом с работой, а не в разделе школы: там отвечают на вопрос
 * администратора «не пора ли поднять потолок», а здесь на вопрос учителя —
 * «во что обошлось вот это чтение». Цена показывается там же, где идёт
 * чтение: узнавать её, уже потратив, — не то же самое, что видеть по ходу.
 *
 * **Одной суммы стало мало, когда читателей стало двое.** Сумма всегда
 * включала всех — и модель, и Mathpix, — но на экране это было неотличимо от
 * прежней цены, а вопрос у учителя ровно противоположный: второй читатель
 * заказывается галочкой на каждой пачке, и решают её по тому, сколько он
 * стоил на прошлой. Число, из которого этого не достать, отвечает не на тот
 * вопрос. Разбивку сервер отдавал и раньше (`by_purpose`), её просто никто не
 * рисовал.
 *
 * Показывается она **только когда поводов больше одного**: на пачке, где
 * читал один, разбивка слово в слово повторяла бы строку выше.
 */
function SpendLine({ spend }) {
  const { t } = useTranslation()
  if (!spend?.calls) return null

  const by = spend.by_purpose || {}
  const parts = [
    ...SPEND_ORDER.filter((purpose) => by[purpose]),
    ...Object.keys(by).filter((purpose) => !SPEND_ORDER.includes(purpose)),
  ]

  return (
    <p className="hint">
      {t('scan.batchSpend', { amount: dollars(spend.micros), count: spend.calls })}
      {spend.total_micros > spend.micros &&
        ` · ${t('scan.workSpend', { amount: dollars(spend.total_micros) })}`}
      {parts.length > 1 && (
        <>
          <br />
          {parts
            .map((purpose) =>
              t('scan.spendPart', {
                what: t(`ai.purpose.${purpose}`),
                amount: dollars(by[purpose].micros),
              }),
            )
            .join(' · ')}
        </>
      )}
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
function CheckStep({ state, pages, busy, hasFile, onFix, onBack, onApply }) {
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
              {/* Предупреждения — свой столбец, а не приписка к сумме. Стояли
                  они рядом с числом, и строка читалась как «итог 14 та же
                  задача дважды»: два разных факта в одной клетке, причём
                  тревожный набран мелким шрифтом при крупном спокойном. */}
              <th>{t('scan.warnings')}</th>
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
                </td>
                <td className="scan-warnings">
                  {student.conflicts.length > 0 && (
                    <span className="hint warning">
                      {t('scan.conflict', { list: student.conflicts.join(', ') })}
                    </span>
                  )}
                  {/* листы одного ученика лежат в стопке подряд — так их и
                      сдают; разрыв почти всегда значит чужую страницу,
                      приписанную по совпавшему покрытию задач */}
                  {student.scattered && (
                    <span className="hint warning">{t('scan.scattered')}</span>
                  )}
                  {/* балл, который скан перепишет, называется до записи:
                      прежний мог быть поставлен за онлайн-ответ или прошлым
                      разбором этой же пачки, и молча заменить его нельзя */}
                  {student.overwrites?.length > 0 && (
                    <span className="hint warning">
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
        {/* Файла может не быть: к уже прочитанной пачке возвращаются кнопкой
            «к страницам», и тогда браузер держит только прочитанное, а сами
            страницы режет отправка. Просим указать тот же PDF — перечитывать
            и платить не придётся, у страниц есть отпечаток. */}
        {hasFile ? (
          <button type="button" disabled={busy} onClick={() => onApply()}>
            {t('scan.apply')}
          </button>
        ) : (
          <label className="button-like">
            <input
              type="file"
              accept="application/pdf"
              hidden
              disabled={busy}
              onChange={(event) => onApply(event.target.files[0])}
            />
            {t('scan.applyNeedsFile')}
          </label>
        )}
        <button type="button" className="secondary" disabled={busy} onClick={onBack}>
          {t('scan.back')}
        </button>
      </div>
    </section>
  )
}
