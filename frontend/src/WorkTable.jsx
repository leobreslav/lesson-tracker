import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import CellDialog from './CellDialog'
import ColumnDialog from './ColumnDialog'
import Markdown from './Markdown'
import { fetchWorkTable } from './api'
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

      <Summary
        summary={table.summary}
        tasks={table.tasks}
        onOpen={(task) => setColumn({ task })}
      />

      {table.tasks.length === 0 ? (
        <p className="hint">{t('works.task.none')}</p>
      ) : (
        <section className="panel table-scroll">
          <table className="work-table">
            <thead>
              <tr>
                <th className="who">{t('table.student')}</th>
                {/* под номером задачи ничего не пишем: числа по столбцу
                    были третьей строкой мелким шрифтом и делали шапку
                    шумной. Кто справился — видно по самой колонке, а
                    подробности живут в окне проверки и в сводке */}
                {table.tasks.map((task, index) => (
                  <th key={task.id}>
                    <button
                      type="button"
                      className="link"
                      title={task.question}
                      onClick={() => setColumn({ task })}
                    >
                      {index + 1}
                    </button>
                  </th>
                ))}
                <th className="total">{t('table.total')}</th>
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
                  {student.cells.map((item) => (
                    <td key={item.task} className={cellClass(item)}>
                      <button
                        type="button"
                        className="cell"
                        title={item.answer ?? t('table.empty')}
                        disabled={!item.submission}
                        onClick={() =>
                          setCell({
                            student,
                            task: table.tasks.find((row) => row.id === item.task),
                          })
                        }
                      >
                        {cellMark(item)}
                      </button>
                    </td>
                  ))}
                  <td className="total">
                    {student.correct}/{table.tasks.length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <details className="panel">
        <summary>{t('table.questions')}</summary>
        <ol className="task-list">
          {table.tasks.map((task, index) => (
            <li key={task.id}>
              {/* номер тот же, что в шапке столбца: по нему их и сличают */}
              <span className="task-number">{index + 1}.</span>
              <div className="task-question">
                <Markdown text={task.question} />
              </div>
            </li>
          ))}
        </ol>
      </details>

      <p>
        <Link to="/works">{t('nav.works')}</Link>
      </p>

      {cell && (
        <CellDialog
          student={cell.student}
          task={cell.task}
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
    </main>
  )
}

/** Состояние ячейки одним словом — из него и складывается вид таблицы. */
function cellClass(item) {
  if (!item.submission) return 'empty'
  if (item.redone) return 'redone'
  if (item.verdict === true) return 'correct'
  if (item.verdict === false) return 'wrong'
  return 'sent'
}

function cellMark(item) {
  if (!item.submission) return ''
  if (item.verdict === true) return '✓'
  if (item.verdict === false) return '✗'
  return item.redone ? '↻' : '•'
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
