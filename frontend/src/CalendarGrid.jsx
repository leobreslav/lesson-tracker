import {
  STATUS_LABELS,
  STATUS_WEEKEND,
  WEEKDAY_SHORT,
  groupByMonth,
  parseDate,
} from './calendarLogic'
import useRangeSelection from './useRangeSelection'

const LEGEND = ['study', 'holiday', 'vacation', 'weekend']

/**
 * Сетка календаря на все месяцы года.
 *
 * Клик по дню переключает его статус, протягивание мышью выделяет диапазон.
 * Одиночный клик диапазоном не считается: mouseup на другой ячейке не
 * порождает click, поэтому обработчики не конфликтуют.
 */
export default function CalendarGrid({
  days,
  pending,
  onToggleDay,
  onSelectRange,
  disabled,
}) {
  const { isSelected, dayProps } = useRangeSelection({ onSelectRange, disabled })

  const highlighted = (date) =>
    // пока диалог спрашивает название, выделение остаётся видимым
    (pending && pending.start_date <= date && date <= pending.end_date) ||
    isSelected(date)

  return (
    <div className="calendar">
      <ul className="legend">
        {LEGEND.map((status) => (
          <li key={status}>
            <span className={`swatch ${status}`} aria-hidden="true" />
            {STATUS_LABELS[status]}
          </li>
        ))}
      </ul>

      <div className="months">
        {groupByMonth(days).map((month) => (
          <section className="month" key={month.key}>
            <h3>{month.label}</h3>
            <div className="month-grid">
              {WEEKDAY_SHORT.map((name) => (
                <div className="weekday" key={name}>
                  {name}
                </div>
              ))}
              {Array.from({ length: month.leading }, (_, index) => (
                <div className="day blank" key={`blank-${index}`} />
              ))}
              {month.days.map((day) => (
                <button
                  type="button"
                  key={day.date}
                  className={
                    `day ${day.status}` +
                    (highlighted(day.date) ? ' selected' : '') +
                    // выходной с пометкой красится как выходной, но точка
                    // показывает, что исключение на нём всё-таки есть
                    (day.exception && day.status === STATUS_WEEKEND ? ' noted' : '')
                  }
                  title={
                    day.title
                      ? `${day.title} (${STATUS_LABELS[day.status].toLowerCase()})`
                      : STATUS_LABELS[day.status]
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
