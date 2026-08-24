import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'
import CellDialog from './CellDialog'
import ColumnDialog from './ColumnDialog'
import GradeDialog from './GradeDialog'
import Markdown from './Markdown'
import Modal from './Modal'
import ScaleDialog from './ScaleDialog'
import SplitDialog from './SplitDialog'
import TaskBrief from './TaskBrief'
import { fetchWorkTable, gradeStudent, saveScale, splitScan } from './api'
import { POLL_MS } from './polling'

/**
 * Сводная таблица работы: ученики по строкам, задачи по столбцам.
 *
 * В ячейке — состояние, а не ответ: пусто, отправлено, верно, неверно, плюс
 * пометка «переделал». Ответ показывается подсказкой при наведении, история
 * — по клику. Иначе таблица на тридцать человек и десять задач читается как
 * простыня текста, а нужна она ровно затем, чтобы **увидеть** столбец, с
 * которым не справилась половина класса.
 *
 * Проверяют чаще столбцом, чем строкой: открыть задачу и пройти ответы
 * подряд — глаз настроен на один эталон. Поэтому по заголовку столбца
 * открывается режим проверки, а по ячейке — только её история.
 */
export default function WorkTable() {
  const { id } = useParams()
  const { t } = useTranslation()
  const [table, setTable] = useState(null)
  const [error, setError] = useState(null)
  const [cell, setCell] = useState(null) // {student, task}
  const [column, setColumn] = useState(null) // {task}
  const [grading, setGrading] = useState(null) // {student}
  const [scaling, setScaling] = useState(false)
  const [question, setQuestion] = useState(null) // условие задачи с листа
  const [splitting, setSplitting] = useState(false)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const version = useRef(null)

  const load = useCallback(
    async ({ polling = false } = {}) => {
      const answer = await fetchWorkTable(id, polling ? version.current : null)
      version.current = answer.version
      // «не изменилось» — не повод перерисовывать: любая перерисовка сбивает
      // выделение и прокрутку у того, кто в этот момент читает ответ
      if (answer.changed !== false) setTable(answer)
    },
    [id],
  )

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  useEffect(() => {
    const timer = setInterval(
      () => load({ polling: true }).catch(() => {}),
      POLL_MS,
    )
    return () => clearInterval(timer)
  }, [load])

  if (table === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  const refresh = () => load().catch((err) => setError(err.message))

  const run = async (request, describe) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await request()
      await load()
      if (describe) setNotice(describe(result))
      setGrading(null)
      setScaling(false)
      setSplitting(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const criteria = table.criteria ?? []
  const scale = {
    criteria,
    graded: criteria.length > 0,
    simple: criteria.length === 1 && !criteria[0].name,
  }
  // столбец «работа ученика» нужен и без оценок: у бумажной работы в нём
  // лежит скан, и это единственное место, где он есть
  /*
   * Что показывать, решают **данные**, а не флаг работы.
   *
   * `on_paper` решал это раньше, и потому смешанный случай был недостижим:
   * у работы, где класс писал онлайн, а сдал на бумаге, половина таблицы
   * оказывалась невидимой. Спрашиваем прямо: есть ли ответы, есть ли
   * приложенные работы, стоит ли шкала.
   */
  const hasPapers = table.students.some((row) => row.papers?.length)
  const hasAnswers = table.tasks.some((task) => task.answered > 0)
  const showRow = scale.graded || hasPapers
  /* У бумажной работы задач нет по определению, а вопросы есть — они и есть
     критерии шкалы. Столбцы по ним отвечают на то, ради чего таблицу и
     открывают: кто что решил и с чем не справился класс. */
  const marks = table.marks_summary
  /* У бумажной работы вопросы те же, что у онлайновой, — колонки общие. В
     ячейке только другое: там балл, а не состояние отправки. */
  const hasMarks = Boolean(marks && marks.columns.length > 0)
  // сумма баллов осмысленна там, где вопрос стоит больше единицы; иначе
  // «сколько верно из скольки» говорит больше
  const pointed = table.tasks.some((task) => task.maximum > 1)
  // максимум за работу: сумма стоимостей вопросов
  const workMaximum = table.tasks.reduce((sum, task) => sum + (task.maximum ?? 0), 0)
  const statsOf = (id) => marks?.columns.find((column) => column.id === id)

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{table.work.title}</h1>
        <p className="hint">
          {table.work.course_name} · {t(`works.state.${table.work.state}`)}
        </p>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="hint" role="status">
          {notice}
        </p>
      )}

      {/* две сводки отвечают на разные вопросы — «как идёт сдача» и «как
          справились», — и работа может иметь обе половины разом */}
      {(hasAnswers || !hasMarks) && (
        <Summary
          summary={table.summary}
          tasks={table.tasks}
          onOpen={(task) => setColumn({ task })}
        />
      )}
      {hasMarks && <MarkSummary summary={marks} />}

      {/* шкала стоит здесь, а не в настройках работы: настраивают её тогда
          же, когда садятся проверять, и это то же самое место */}
      <p className="hint scale-line">
        {describeScale(scale, t)}{' '}
        <button
          type="button"
          className="link"
          disabled={busy}
          onClick={() => setScaling(true)}
        >
          {t('grading.configure')}
        </button>
        {' · '}
        <button
          type="button"
          className="link"
          disabled={busy}
          onClick={() => setSplitting(true)}
        >
          {t('split.action')}
        </button>
      </p>

      {/* таблица нужна и без задач: у бумажной работы в ней сканы и
          оценки, а задач нет по определению */}
      {table.tasks.length === 0 && !showRow ? (
        <p className="hint">{t('works.task.none')}</p>
      ) : (
        <section className="panel table-scroll">
          <table className="work-table">
            <thead>
              <tr>
                {/*
                  * Вторую строку шапки **называет** подпись у правого края
                  * столбца имени. Без неё скобки под именами столбцов — просто
                  * числа неизвестно о чём, и читаются они как ещё один балл.
                  *
                  * Своим столбцом она была, и трижды не попадала в ритм:
                  * заданный отступ не следит за шириной столбцов задач, а та
                  * меняется от числа вопросов. Прижатая к краю имени, подпись
                  * следит за ней сама.
                  */}
                <th className="who">
                  <span className="head-name">{t('table.student')}</span>
                  <span className="head-max">{t('table.maximum')}</span>
                </th>
                {/* под номером задачи ничего не пишем: числа по столбцу
                    были третьей строкой мелким шрифтом и делали шапку
                    шумной. Кто справился — видно по самой колонке, а
                    подробности живут в окне проверки и в сводке */}
                {table.tasks.map((task) => (
                  <th
                    key={task.id}
                    className={hasMarks && task.id === marks.hardest ? 'hardest' : ''}
                    title={
                      task.question ||
                      (hasMarks
                        ? t('grading.facility', {
                            percent: statsOf(task.id)?.facility ?? 0,
                          })
                        : '')
                    }
                  >
                    <button
                      type="button"
                      className="link"
                      onClick={() =>
                        /* Номер вопроса открывает **вопрос**: что спрашивали
                           и что считается верным. Открывал он то колонку
                           ответов, то сводку по столбцу — и на бумажной
                           работе, где сводки ещё нет, не открывал ничего
                           вовсе: `statsOf` возвращал пустоту, и нажатие
                           уходило в никуда. Колонка ответов при этом никуда
                           не делась: в неё ведёт сводка сдачи над таблицей,
                           где ей и место — там про ответы, а тут про
                           условие. */
                        setQuestion({ task, stats: statsOf(task.id) })
                      }
                    >
                      {task.name}
                    </button>
                    {/* сколько стоит вопрос: без этого балл в клетке — число
                        без шкалы, и «2» у одного вопроса и «2» у другого
                        читаются одинаково, хотя значат разное */}
                    <span className="head-max">{`(${task.maximum})`}</span>
                  </th>
                ))}
                {showRow && (
                  <th className="mark">
                    {/* Вторая строка пустая, но она **есть**: подписи столбцов
                        стоят на одной линии только тогда, когда строк у всех
                        поровну. Без неё «Работа» опускалась к низу клетки, а
                        соседний «Итог» держался строкой выше — и выглядело
                        это как разные уровни и разный цвет. */}
                    <span className="head-name">
                      {t(scale.graded ? 'grading.mark' : 'paper.column')}
                    </span>
                    <span className="head-max">{'\u00A0'}</span>
                  </th>
                )}
                {table.tasks.length > 0 && (
                  <th className="total">
                    <span className="head-name">{t('table.total')}</span>
                    {/* максимум за работу — под именем столбца: «14» без «из
                        18» не говорит ничего, а искать его было негде */}
                    <span className="head-max">
                      {pointed ? `(${workMaximum})` : '\u00A0'}
                    </span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {table.students.map((student) => (
                <tr key={student.id} className={student.active ? '' : 'past'}>
                  <th className="who">
                    {student.name}
                    {!student.active && (
                      <span className="hint"> {t('table.removed')}</span>
                    )}
                  </th>
                  {/* клетка одна на оба случая: в ней балл, а если его нет —
                      состояние ответа. Двух видов таблицы больше нет */}
                  {student.cells.map((item) => (
                        <td key={item.task} className={cellClass(item)}>
                          <button
                            type="button"
                            className="cell"
                            title={
                              item.seen_before
                                ? t('table.seenBefore', { count: item.seen_before })
                                : (item.answer ?? t('table.empty'))
                            }
                            onClick={() =>
                              /* Клик по клетке открывает **эту** клетку —
                                 всегда. Раньше он вёл в окно ячейки только
                                 при отправке или снимке, а у бумажной работы
                                 не бывает ни того, ни другого: клик уводил в
                                 оценку всей работы, то есть в пятнадцать
                                 чужих вопросов вместо одного нужного. Между
                                 тем разбирают именно клетку: её балл, её
                                 снимки, разговор про неё. */
                              setCell({
                                student,
                                cell: item,
                                task: table.tasks.find((row) => row.id === item.task),
                              })
                            }
                          >
                            {cellMark(item)}
                            {/* пришёл новый ответ, а балл стоит за прошлый:
                                точка зовёт посмотреть, но ничего не решает
                                за учителя */}
                            {item.stale && <i className="review" />}
                            {/* эту задачу он уже решал в другой работе:
                                уголок, а не строка — в клетке нет места, а
                                знать это надо при проверке */}
                            {item.seen_before > 0 && <i className="again" />}
                            {/* прислана фотография решения. Без этого знака
                                сданная тетрадью задача выглядит нерешённой:
                                поля ответа у неё нет, и клетка пуста */}
                            {item.photos > 0 && <i className="shot" />}
                          </button>
                        </td>
                  ))}
                  {showRow && (
                    <td className="mark">
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        onClick={() => setGrading({ student })}
                      >
                        {showMarks(student.marks, criteria) ||
                          (student.papers?.length ? '📄' : '—')}
                      </button>
                    </td>
                  )}
                  {table.tasks.length > 0 && (
                    <td className="total">
                      {pointed
                        ? Object.values(student.scores).reduce(
                            (sum, one) => sum + one,
                            0,
                          ) || ''
                        : `${student.correct}/${table.tasks.length}`}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <details className="panel">
        <summary>{t('table.questions')}</summary>
        <ol className="task-list">
          {table.tasks.map((task) => (
            <li key={task.id}>
              {/* имя то же, что в шапке столбца: по нему их и сличают */}
              <span className="task-number">{task.name}.</span>
              <div className="task-question">
                <Markdown text={task.question} />
              </div>
            </li>
          ))}
        </ol>
      </details>

      {question && (
        <Modal
          onClose={() => setQuestion(null)}
          title={t('grading.questionTitle', { name: question.task.name })}
        >
          {/* условие и эталоны — тем же компонентом, что и в окне ячейки:
              вопрос «что тут спрашивали» один и тот же */}
          <TaskBrief task={question.task} />
          <p className="hint">
            {t('table.markPoints', { value: '', maximum: question.task.maximum })}
          </p>
          {/* «как справились» — только когда справлялись: у работы, где ещё
              никого не проверяли, ноль процентов означал бы неверное */}
          {question.stats && (
            <p className="hint">
              {t('grading.facility', { percent: question.stats.facility ?? 0 })} ·{' '}
              {t('grading.hardestBreakdown', {
                full: question.stats.full,
                partial: question.stats.partial,
                zero: question.stats.zero,
              })}
            </p>
          )}

          {/* Проверка столбцом — отсюда же. Номер вопроса вёл прямо в неё, и
              условие посмотреть было негде; но и убрать её из-под номера
              нельзя: столбец проверяют именно так, подряд по вопросу. Поэтому
              сперва условие, а проверка соседней кнопкой. */}
          {question.task.answered > 0 && (
            <div className="actions">
              <button
                type="button"
                onClick={() => {
                  const task = question.task
                  setQuestion(null)
                  setColumn({ task })
                }}
              >
                {t('table.checkColumn')}
              </button>
            </div>
          )}
        </Modal>
      )}

      {cell && (
        <CellDialog
          work={table.work.id}
          student={cell.student}
          task={cell.task}
          cell={cell.cell}
          onChanged={refresh}
          onClose={() => setCell(null)}
        />
      )}

      {column && (
        <ColumnDialog
          task={column.task}
          onChanged={refresh}
          onClose={() => setColumn(null)}
        />
      )}

      {scaling && (
        <ScaleDialog
          work={table.work.id}
          scale={scale}
          busy={busy}
          onSubmit={(rows) => run(() => saveScale(table.work.id, rows))}
          onClose={() => setScaling(false)}
        />
      )}

      {splitting && (
        <SplitDialog
          students={table.students}
          busy={busy}
          onSubmit={(payload) =>
            run(
              () => splitScan(table.work.id, payload),
              (result) => t('split.done', { created: result.created }),
            )
          }
          onClose={() => setSplitting(false)}
        />
      )}

      {grading && (
        <GradeDialog
          work={table.work.id}
          student={
            // строка берётся из свежей таблицы: после загрузки скана окно
            // должно показать его, не закрываясь
            table.students.find((row) => row.id === grading.student.id) ??
            grading.student
          }
          criteria={criteria}
          tasks={table.tasks}
          busy={busy}
          onSubmit={(body) => run(() => gradeStudent(table.work.id, body))}
          onChanged={refresh}
          onClose={() => setGrading(null)}
        />
      )}
    </main>
  )
}

/** Оценки в клетке: одна отметка или набор по критериям через точку. */
function showMarks(marks, criteria) {
  const values = criteria.map((item) => marks?.[item.id])
  if (values.every((value) => value === undefined)) return ''

  return values.map((value) => (value === undefined ? '–' : value)).join(' · ')
}

/** Чем оценивается работа, одной фразой над таблицей. */
function describeScale(scale, t) {
  if (!scale.graded) return t('grading.notGraded')
  if (scale.simple) return t('grading.outOf', { maximum: scale.criteria[0].maximum })

  return t('grading.byCriteria', {
    names: scale.criteria.map((item) => item.name).join(', '),
  })
}

/** Состояние ячейки одним словом — из него и складывается вид таблицы. */
/**
 * Цвет ячейки по доле балла: полный, частичный, ноль.
 *
 * Те же три состояния, что у проверки онлайн, и те же классы — один факт
 * должен выглядеть одинаково везде, где его показывают.
 */
/**
 * Сводка по оценкам бумажной работы.
 *
 * Отвечает на то, чего таблица одним взглядом не говорит: сколько работ
 * разобрано, как класс написал в целом и что далось труднее всего. Остальное
 * — кто что решил — стоит в самой таблице, и повторять это плашками значит
 * заставлять читать одно и то же дважды.
 */
function MarkSummary({ summary }) {
  const { t } = useTranslation()
  const hardest = summary.columns.find((column) => column.id === summary.hardest)

  return (
    <div className="cards work-summary">
      <section className="panel card-stat stat-rows" data-card="graded">
        <b>{summary.graded}</b>
        <span className="hint">{t('grading.gradedLabel')}</span>
        <b>{summary.mean ?? '—'}</b>
        <span className="hint">{t('grading.meanLabel', { max: summary.max_total })}</span>
        <span className="hint total">
          {t('table.studentsTotal', { count: summary.students })}
        </span>
      </section>

      {/* медиана рядом со средним: одна двойка среди отличников тянет
          среднее, а медиану — нет, и вместе они говорят про класс больше */}
      <section className="panel card-stat stat-rows" data-card="spread">
        <b>{summary.median ?? '—'}</b>
        <span className="hint">{t('grading.medianLabel')}</span>
        <b>
          {summary.worst ?? '—'}–{summary.best ?? '—'}
        </b>
        <span className="hint">{t('grading.spreadLabel')}</span>
      </section>

      {hardest && (
        <section className="panel card-stat" data-card="hardest">
          <h2>{hardest.name}</h2>
          <p className="hint">
            {t('grading.hardestLabel', { percent: hardest.facility })}
          </p>
          <p className="hint">
            {t('grading.hardestBreakdown', {
              full: hardest.full,
              partial: hardest.partial,
              zero: hardest.zero,
            })}
          </p>
        </section>
      )}
    </div>
  )
}

/*
 * Клетка: балл, если он поставлен, и состояние ответа, если ещё нет.
 *
 * Ось одна — «что он решил», — и состояний у неё четыре: не присылал,
 * прислал и ждёт, прислал и получил балл, получил балл и прислал ещё раз.
 * Галочка выражала только два крайних, а частичный балл онлайн поставить
 * было негде вовсе.
 *
 * `stale` — «пришёл новый ответ после того, как балл поставлен». Балл при
 * этом **виден**, а не гаснет: стирать работу учителя за то, что ученик
 * прислал ещё раз, нельзя. Рядом с баллом стоит точка «надо посмотреть», и
 * решает человек.
 */
function cellClass(item) {
  if (!item.submission && item.mark === null) return 'empty'
  if (item.stale) return 'stale'
  if (item.mark === null) return 'sent'
  if (item.mark >= item.maximum) return 'correct'
  if (item.mark === 0) return 'wrong'
  return 'partial'
}

function cellMark(item) {
  if (item.mark === null || item.mark === undefined) {
    return item.submission ? '•' : ''
  }
  // У вопроса из одного балла балл — это и есть галочка, и рисовать его
  // цифрой значит сделать таблицу хуже: тридцать человек на десять задач
  // читают через комнату, а «1» и «0» различаются слабее, чем ✓ и ✗.
  // Цифра появляется там, где она что-то говорит, — где баллов больше.
  if (item.maximum === 1) return item.mark >= 1 ? '✓' : '✗'
  return item.mark
}


/**
 * Сводка над таблицей: то, чего таблица не говорит одним взглядом.
 *
 * Две плашки, и обе про работу учителя. Продвижение класса — одно число с
 * двумя половинами: сколько начали и сколько дошли до конца; врозь они
 * читались бы как два разных показателя, хотя это одна дробь и её остаток.
 * Вторая — сколько ответов ждёт проверки, и она кликабельна: число, на
 * которое нельзя нажать, заставляет искать его источник руками.
 *
 * «Самой трудной задачи» здесь нет намеренно: числа по столбцу и так
 * стоят в его шапке, а плашка повторяла их отдельно.
 */
function Summary({ summary, tasks, onOpen }) {
  const { t } = useTranslation()

  if (!summary) return null

  const waiting = tasks.find((task) => task.unchecked > 0)

  return (
    <div className="cards work-summary">
      {/* две равноценные строки: «начали» и «прошли целиком» — разные
          вопросы к одному классу, и одна не подпись к другой. Сколько
          человек всего — внизу и мелким: это знаменатель обеих строк, и
          повторять его дважды незачем */}
      <section className="panel card-stat stat-rows" data-card="started">
        <b>{summary.started}</b>
        <span className="hint">{t('table.startedLabel')}</span>
        <b>{summary.finished}</b>
        <span className="hint">{t('table.finishedLabel')}</span>
        <span className="hint total">
          {t('table.studentsTotal', { count: summary.students })}
        </span>
      </section>

      <section className="panel card-stat" data-card="unchecked">
        {waiting ? (
          <button type="button" className="link" onClick={() => onOpen(waiting)}>
            <h2>{summary.unchecked}</h2>
          </button>
        ) : (
          <h2>{summary.unchecked}</h2>
        )}
        <p className="hint">{t('table.uncheckedLabel')}</p>
      </section>
    </div>
  )
}
