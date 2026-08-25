import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { dayMonth, longDate } from './dates'

/**
 * Журнал курса: ученики по строкам, занятия по столбцам.
 *
 * Одна таблица на обе стороны — учительскую и семейную, — и это то же
 * решение, что у расчёта на сервере: пока вопрос один («как идёт курс»),
 * ответов должно быть два (весь класс или своя строка), но рисунок один.
 * Разойдись он, и родитель на собрании увидел бы не то, что учитель у себя.
 *
 * **Столбец — это занятие, а не работа.** Работ на одном занятии бывает
 * несколько, а бывает ни одной — и тогда столбец всё равно нужен, в нём
 * стоит посещаемость. Столбцы без даты в конце — работы, не привязанные к
 * занятию: контрольная за четверть, пересдача.
 *
 * **В шапке две ссылки, и они про разное.** Дата ведёт на занятие («что там
 * было»), значок работы — на саму работу («что задали и как проверено»).
 * Значок односимвольный не от жадности: столбцов до семидесяти, и название
 * работы в шапке сделало бы таблицу нечитаемой в любом языке. Полное имя
 * приезжает подсказкой при наведении, а что значит буква — сказано легендой
 * под таблицей, один раз на весь экран.
 *
 * **Посещаемость стоит в той же клетке**, под оценками. Врозь это были бы две
 * таблицы с одинаковой шапкой, и читать их пришлось бы, ведя пальцем по двум
 * экранам сразу. «Не отмечено» при этом пусто, а «был» — точка: различать их
 * обязательно, пустой журнал и журнал, где весь класс отсутствовал, — разные
 * вещи.
 */
export default function JournalTable({ journal, lessonLinks = true }) {
  const { t } = useTranslation()
  const columns = journal.columns ?? []
  const students = journal.students ?? []

  if (columns.length === 0) {
    return <p className="hint">{t('journal.noLessons')}</p>
  }

  return (
    <>
      <div className="table-scroll">
        <table className="journal-table">
          <thead>
            <tr>
              <th className="who">{t('journal.student')}</th>
              {columns.map((column, at) => (
                <th key={at} className={headClass(column)}>
                  {column.date ? (
                    lessonLinks ? (
                      <Link
                        to={`/lesson/${column.slot}`}
                        className="day"
                        title={longDate(column.date)}
                      >
                        {dayMonth(column.date)}
                      </Link>
                    ) : (
                      <span className="day" title={longDate(column.date)}>
                        {dayMonth(column.date)}
                      </span>
                    )
                  ) : (
                    /* у работы без занятия даты нет, и ставить сюда дату её
                       окна значило бы выдумать день, в который ничего не
                       происходило */
                    <span className="day off">{t('journal.noDate')}</span>
                  )}

                  <span className="heads">
                    {column.works.map((work) => (
                      <Link
                        key={work.id}
                        to={`/works/${work.id}`}
                        className={`work-tag ${kindOf(work)}`}
                        title={work.title}
                      >
                        {t(`journal.tag.${kindOf(work)}`)}
                      </Link>
                    ))}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {students.map((row) => (
              <tr key={row.id} className={row.active === false ? 'past' : ''}>
                <th className="who">
                  {row.name}
                  {row.active === false && (
                    <span className="hint"> {t('table.removed')}</span>
                  )}
                </th>
                {row.cells.map((cell, at) => (
                  <td key={at} className={cellClass(columns[at], cell)}>
                    <span className="marks">
                      {cell.marks.map((mark) => (
                        <Link
                          key={mark.work}
                          to={`/works/${mark.work}`}
                          className="mark"
                          title={titleOf(columns[at], mark)}
                        >
                          {mark.label}
                        </Link>
                      ))}
                    </span>
                    {cell.attendance && (
                      <span
                        className={`att ${cell.attendance}`}
                        title={
                          cell.note ||
                          t(`journal.attendance.${cell.attendance}`)
                        }
                      >
                        {t(`journal.att.${cell.attendance}`)}
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Легенда одна на весь экран, а не подпись у каждой буквы: буквы
          повторяются в семидесяти столбцах, и объяснять их по месту значило
          бы заслонить объяснением сам журнал. */}
      <p className="hint journal-legend">
        {t('journal.legend', {
          summative: t('journal.tag.summative'),
          homework: t('journal.tag.homework'),
          work: t('journal.tag.work'),
          absent: t('journal.att.absent'),
          late: t('journal.att.late'),
          present: t('journal.att.present'),
        })}
      </p>
    </>
  )
}

/** Вид работы одним словом: по нему выбирается и значок, и цвет. */
function kindOf(work) {
  if (work.is_summative) return 'summative'
  if (work.is_homework) return 'homework'
  return 'work'
}

/** Отменённый час помечен в шапке: клетки в нём быть не должно. */
function headClass(column) {
  const marks = []
  if (column.is_cancelled) marks.push('cancelled')
  if (column.is_extra) marks.push('extra')
  if (!column.past) marks.push('ahead')
  return marks.join(' ')
}

function cellClass(column, cell) {
  const marks = []
  if (column?.is_cancelled) marks.push('cancelled')
  if (!column?.past) marks.push('ahead')
  if (cell.attendance === 'absent') marks.push('missed')
  return marks.join(' ')
}

/**
 * Подсказка у отметки: чья она и из чего вышла.
 *
 * «5» в клетке ничего не говорит о том, за что она, а столбцов много и
 * возвращаться к шапке глазами дорого. Поэтому имя работы едет сюда же, а
 * рядом — сумма баллов, если система их считала.
 */
function titleOf(column, mark) {
  const work = (column?.works ?? []).find((one) => one.id === mark.work)
  const name = work ? work.title : ''
  const score = mark.top ? ` (${mark.earned}/${mark.top})` : ''
  return `${name}${score}`
}
