import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import CellDialog from './CellDialog'
import ColumnDialog from './ColumnDialog'
import Markdown from './Markdown'
import { fetchWorkTable } from './api'

// опрос: тридцать учеников нагрузки не создают, а ответ «ничего не
// изменилось» стоит один агрегат — версия и заведена ради этого
const POLL_MS = 3000

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
          {table.work.course_name} · {t(`works.state.${table.work.state}`)} ·{' '}
          {t('table.answered', {
            students: table.students.filter((row) => row.answered).length,
            total: table.students.length,
          })}
        </p>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {table.tasks.length === 0 ? (
        <p className="hint">{t('works.task.none')}</p>
      ) : (
        <div className="table-scroll">
          <table className="work-table">
            <thead>
              <tr>
                <th className="who">{t('table.student')}</th>
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
                    <span className="hint">
                      {task.unchecked > 0
                        ? t('table.unchecked', { count: task.unchecked })
                        : t('table.correctOf', {
                            correct: task.correct,
                            answered: task.answered,
                          })}
                    </span>
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
                        onClick={() => setCell({ student, task: item.task })}
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
        </div>
      )}

      <details className="panel">
        <summary>{t('table.questions')}</summary>
        <ol className="task-list">
          {table.tasks.map((task) => (
            <li key={task.id}>
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
          taskId={cell.task}
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
