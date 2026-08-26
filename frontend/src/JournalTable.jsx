import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { dayMonth, longDate } from './dates'
import { columnWidths } from './journalLayout'

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
 * **Посещаемость стоит в той же клетке**, крайней правой подколонкой. Врозь
 * это были бы две таблицы с одинаковой шапкой, и читать их пришлось бы, ведя
 * пальцем по двум экранам сразу. «Не отмечено» при этом пусто, а «был» —
 * точка: различать их обязательно, пустой журнал и журнал, где весь класс
 * отсутствовал, — разные вещи.
 *
 * **Дата делится на подколонки один раз: сколько работ, столько и колонок,
 * плюс одна на присутствие.** Значки работ идут в ряд, оценка встаёт ровно под
 * своей работой (для неоценённой держится пустое место — иначе следующая
 * съехала бы под чужую), а присутствие прибито к правому краю. Кнопка
 * «завести работу» стоит там же, справа: она не ещё один значок в ряду, а
 * шапка колонки присутствия.
 *
 * **`onAddWork` — единственное, чем таблица пишет**, и передаёт его только
 * учительская сторона. Кнопка стоит в шапке столбца с датой: журнал — то
 * место, где видно пустую клетку, и до сих пор из него приходилось уходить,
 * чтобы её заполнить. У столбцов без занятия кнопки нет: работу заводят
 * **на урок**, а «без занятия» — это его отсутствие, а не место.
 */
export default function JournalTable({ journal, lessonLinks = true, onAddWork = null }) {
  const { t } = useTranslation()
  const columns = journal.columns ?? []
  const students = journal.students ?? []

  /* Ширины подколонок — одним расчётом на шапку и клетку разом
     (`journalLayout.js`, там же почему `rem`, а не `ch`). */
  const widths = useMemo(() => columnWidths(columns, students), [columns, students])

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
                  {/* дата и пометка о записи — одной строкой: пометка про этот
                      день, а не про работы под ним, и уехав вниз она читалась
                      бы как ещё один значок в их ряду */}
                  <span className="dayrow">
                  {column.date ? (
                    lessonLinks ? (
                      <Link
                        to={`/lesson/${column.slot}`}
                        className="day-link"
                        title={longDate(column.date)}
                      >
                        {dayMonth(column.date)}
                      </Link>
                    ) : (
                      <span className="day-link" title={longDate(column.date)}>
                        {dayMonth(column.date)}
                      </span>
                    )
                  ) : (
                    /* у работы без занятия даты нет, и ставить сюда дату её
                       окна значило бы выдумать день, в который ничего не
                       происходило */
                    <span className="day-link off">{t('journal.noDate')}</span>
                  )}

                  {/* Прошло ли занятие по программе: галочка — учитель
                      отметил, какой урок здесь прошёл (`Slot.lesson`), точка —
                      час миновал, а записи нет.

                      Спрашивается это только у **прошедших** и не отменённых:
                      у будущего часа записи и быть не может, а точка на нём
                      читалась бы как долг. Отменённый час помечен сам собой —
                      и записи с него не спрашивают вовсе. */}
                  {column.slot && column.past && !column.is_cancelled && (
                    <span
                      className={`held ${column.lesson ? 'yes' : 'no'}`}
                      title={
                        column.lesson
                          ? t('journal.held', { title: column.lesson.title })
                          : t('journal.notHeld')
                      }
                    >
                      {column.lesson ? '✓' : ''}
                    </span>
                  )}
                  </span>

                  {/* День без работ — это не день с пустым местом слева.
                      Колонка присутствия остаётся единственной и встаёт по
                      центру: делить в таком столбце нечего, а прижатая вправо
                      она читалась бы как «здесь что-то потеряли». */}
                  <span className={`heads${column.works.length ? '' : ' alone'}`}>
                    {/* значок лежит **в подколонке**, а не сам по себе:
                        подколонка держит ширину, значок — только вид. Пока
                        ширину держал сам значок, полосы шапки и клетки
                        совпадали по краям, но не по середине: зазор между
                        значками доставался соседу справа, и всё, кроме первой
                        подколонки, читалось сдвинутым влево */}
                    {column.works.map((work, order) => (
                      <span
                        key={work.id}
                        className="head-cell"
                        style={{ width: widths[at][order] }}
                      >
                        <Link
                          to={`/works/${work.id}`}
                          className={`work-tag ${kindOf(work)}`}
                          title={work.title}
                        >
                          {t(`journal.tag.${kindOf(work)}`)}
                        </Link>
                      </span>
                    ))}
                    {/* кнопка стоит не сама по себе, а в **колонке
                        присутствия**: колонка эта забирает всю ширину, что
                        осталась от работ (столбец шире их почти всегда — его
                        растягивает дата), и содержимое в ней по центру. Иначе
                        кнопка жалась к правому краю, а отметка под ней — к
                        левому: обе «выровнены», и обе не там */}
                    {onAddWork && column.slot && (
                      <span className="att-head">
                      <button
                        type="button"
                        className="work-tag add"
                        title={t('journal.addWork', {
                          date: longDate(column.date),
                        })}
                        aria-label={t('journal.addWork', {
                          date: longDate(column.date),
                        })}
                        onClick={() => onAddWork(column)}
                      >
                        +
                      </button>
                      </span>
                    )}
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
                    {/* Место под каждую работу столбца, а не список одних
                        поставленных оценок. Работы в шапке стоят в ряд, и
                        оценка обязана стоять **под своей**: пропусти
                        неоценённую — и все следующие в этой клетке съедут
                        влево, то есть встанут под чужой работой. Пустое место
                        тут не украшение, а то, чем держится столбец. */}
                    <span
                      className={`marks${columns[at].works.length ? '' : ' alone'}`}
                    >
                      {columns[at].works.map((work, order) => {
                        const mark = cell.marks.find((one) => one.work === work.id)

                        return mark ? (
                          <Link
                            key={work.id}
                            to={`/works/${work.id}`}
                            className="mark"
                            style={{ width: widths[at][order] }}
                            title={titleOf(columns[at], mark)}
                          >
                            {mark.label}
                          </Link>
                        ) : (
                          <span
                            key={work.id}
                            className="mark none"
                            style={{ width: widths[at][order] }}
                            aria-hidden="true"
                          />
                        )
                      })}

                      {/* Посещаемость — **своя подколонка**, крайняя справа, и
                          шапка у неё та самая кнопка «завести работу». Раньше
                          она стояла вторым этажом под оценками, и клетка
                          читалась двумя разными способами: слева направо для
                          оценок и сверху вниз для присутствия. Теперь дата
                          делится на колонки один раз: сколько работ, столько
                          и колонок, плюс одна на присутствие. */}
                      {/* колонка присутствия стоит всегда, когда есть занятие,
                          — даже если этого ученика не отмечали. Рисуй её по
                          наличию отметки, и черта, отделяющая её от оценок,
                          пропадала бы в каждой неотмеченной строке: вместо
                          сплошной вертикали выходил бы пунктир. Пусто и
                          «отсутствовал» при этом по-прежнему разные вещи —
                          пустая клетка ничего не утверждает */}
                      {columns[at].slot && (
                        <span
                          className={`att ${cell.attendance ?? 'unknown'}`}
                          title={
                            cell.attendance
                              ? cell.note ||
                                t(`journal.attendance.${cell.attendance}`)
                              : undefined
                          }
                        >
                          {cell.attendance
                            ? t(`journal.att.${cell.attendance}`)
                            : ''}
                        </span>
                      )}
                    </span>
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
