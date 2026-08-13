import { useTranslation } from 'react-i18next'
import { STATUS_WEEKEND, groupByMonth, parseDate } from './calendarLogic'
import { firstWeekday, monthTitle, weekdayHeadings } from './dates'
import { termColorIndex } from './termColors'
import useRangeSelection from './useRangeSelection'

const LEGEND = ['study', 'holiday', 'vacation', 'weekend']

/**
 * What the colours mean.
 *
 * Lives above both columns rather than inside the calendar: the same
 * swatches are used in the summary on the right, and standing inside the
 * left column the legend pushed the months down — the two columns started at
 * different heights.
 *
 * Statuses and terms are two rows on purpose: the first says what a day is,
 * the second which term it falls into, and a day has both at once.
 */
export function CalendarLegend({ terms = [] }) {
  const { t } = useTranslation()

  return (
    <div className="legends">
      <ul className="legend">
        {LEGEND.map((status) => (
          <li key={status}>
            <span className={`swatch ${status}`} aria-hidden="true" />
            {t(`dayStatus.${status}`)}
          </li>
        ))}
        <li>
          <span className="swatch noted" aria-hidden="true" />
          {t('calendar.legend.noted')}
        </li>
      </ul>

      {terms.length > 0 && (
        <ul className="legend">
          {terms.map((term) => (
            <li key={term.id}>
              <span
                className={`swatch term-${termColorIndex(terms, term.id)}`}
                aria-hidden="true"
              />
              {term.name}
            </li>
          ))}
          <li>
            <span className="swatch no-term" aria-hidden="true" />
            {t('calendar.legend.noTerm')}
          </li>
        </ul>
      )}
    </div>
  )
}

/**
 * The calendar grid across every month of the year.
 *
 * A click toggles the status of a day, dragging selects a range. A single
 * click is not a range: releasing over another cell produces no click there,
 * so the two handlers never collide.
 *
 * The column order follows the language — Monday first in Russian, Sunday in
 * American English — while the weekday numbers stay ours.
 */
export default function CalendarGrid({
  days,
  terms = [],
  pending,
  onToggleDay,
  onSelectRange,
  disabled,
}) {
  const { t } = useTranslation()
  const { isSelected, dayProps } = useRangeSelection({ onSelectRange, disabled })
  const headings = weekdayHeadings()

  const highlighted = (date) =>
    // while the dialog asks for a name, the selection stays visible
    (pending && pending.start_date <= date && date <= pending.end_date) ||
    isSelected(date)

  return (
    <div className="calendar">
      <div className="months">
        {groupByMonth(days, firstWeekday()).map((month) => (
          <section className="month" key={month.key}>
            <h3>{monthTitle(month.first)}</h3>
            <div className="month-grid">
              {headings.map((heading) => (
                <div className="weekday" key={heading.weekday}>
                  {heading.label}
                </div>
              ))}
              {Array.from({ length: month.leading }, (_, index) => (
                <div className="day blank" key={`blank-${index}`} />
              ))}
              {month.days.map((day) => (
                <button
                  type="button"
                  key={day.date}
                  // браузерные тесты целятся по дате: по тексту числа
                  // попасть в нужный месяц нельзя
                  data-date={day.date}
                  className={
                    `day ${day.status}` +
                    (day.term_id
                      ? ` term-${termColorIndex(terms, day.term_id)}`
                      : ' no-term') +
                    (highlighted(day.date) ? ' selected' : '') +
                    // a marked weekend is still painted as a weekend, but the
                    // dot shows the markup is there
                    (day.exception && day.status === STATUS_WEEKEND ? ' noted' : '')
                  }
                  title={
                    day.title
                      ? `${day.title} (${t(`dayStatus.${day.status}`).toLowerCase()})`
                      : t(`dayStatus.${day.status}`)
                  }
                  disabled={disabled}
                  {...dayProps(day.date)}
                  onClick={() => onToggleDay(day.date)}
                >
                  {parseDate(day.date).getDate()}
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
