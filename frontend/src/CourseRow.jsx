import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { longDate, shortDate, shortWeekday } from './dates'

/**
 * Строка состояния плана: свёрнутая шапка и подробности под ней.
 *
 * Один компонент на два экрана. Учитель видит эти строки на главной по
 * своим курсам, методист — в разделе «На утверждение» по чужим, и числа у
 * них обязаны совпадать: разговор про «отстаёшь» не должен начинаться со
 * спора о цифрах. Сервер их и считает одним расчётом (`plans/progress.py`),
 * а здесь одна разметка, чтобы не разошлось и оформление.
 *
 * Различия страниц приезжают пропсами: `mark` — то, что дописывается в
 * шапку (у методиста это имя учителя и пометка «ждёт утверждения»),
 * `actions` — кнопки под подробностями.
 */
export default function CourseRow({
  row: course,
  open,
  onToggle,
  own = false,
  mark,
  actions,
  onCloseDebts,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  /** Всё сводится к одному: план помещается в год или нет. */
  const short = (course) => course.reserve < 0

  const statusText = (course) =>
    short(course)
      ? t('status.status.short', { count: -course.reserve })
      : t('status.status.fine')

  /** «урок 14 из 44 · Тригонометрия». */
  const whereText = (course) => {
    if (!course.lessons_total) return t('status.where.noPlan')
    if (!course.current) return t('status.where.finished', { count: course.done })

    return [
      t('status.where.at', {
        number: course.current.number,
        total: course.lessons_total,
      }),
      course.current.section_title,
    ]
      .filter(Boolean)
      .join(' · ')
  }

  const signed = (value) => `${value > 0 ? '+' : ''}${value}`

  /**
   * Прогресс по плану: три связанных числа одной плашкой.
   *
   * Проведено, осталось и всего — это одно утверждение, разложенное на
   * три части, и врозь они читаются как три разных показателя.
   *
   * Дефицит на числа не влияет: «осталось 30» значит тридцать уроков
   * плана, а хватит ли им дней — отдельный вопрос, и у него своё
   * предупреждение в шапке.
   */
  const progressCard = (course) => {
    if (!course.lessons_total) {
      return (
        <section className="panel card-stat" data-card="progress">
          <p className="hint">{t('status.where.noPlan')}</p>
          {/* кнопка ведёт в **свой** план, поэтому только у своего курса:
              методист смотрит чужой, и звать его заполнять нечего */}
          {own && (
            <button type="button" className="link" onClick={() => navigate('/plan')}>
              {t('status.fillPlan')}
            </button>
          )}
        </section>
      )
    }

    const left = course.lessons_total - course.done

    return (
      <section className="panel card-stat" data-card="progress">
        <h2>{t('status.doneOf', { done: course.done, total: course.lessons_total })}</h2>
        <p className="hint">{t('status.left', { count: left })}</p>
      </section>
    )
  }

  const details = (course) => (
    <div className="progress-details">
      <div className="cards">
        {progressCard(course)}

        <section
          className={`panel card-stat ${short(course) ? 'bad' : 'good'}`}
          data-card="reserve"
        >
          <h2>{signed(course.reserve)}</h2>
          <p className="hint">
            {t(short(course) ? 'status.reserveShort' : 'status.reserveSpare')}
          </p>
          {/* Резерв — единственное число, живущее сразу на обеих осях, и
              потому его падение само по себе ничего не объясняет: то ли дни
              потерялись, то ли план вырос. С точкой отсчёта (эталон помнит,
              сколько было часов) это уже тождество, а не догадка. */}
          {course.baseline?.reserve && (
            <p className="hint">
              {t('status.reserveWhy', {
                then: signed(course.baseline.reserve.then),
                schedule: signed(course.baseline.reserve.schedule),
                plan: signed(-course.baseline.reserve.plan),
              })}
            </p>
          )}
        </section>

        {/* насколько расписание разошлось с исходным: добавили минус
            отменили. С резервом не путать — тот про план, этот про дни */}
        <section className="panel card-stat" data-card="changes">
          <h2>{signed(course.extra - course.cancelled)}</h2>
          <p className="hint">{t('status.changes')}</p>
          <p className="hint">
            {t('status.changesDetail', {
              cancelled: course.cancelled,
              extra: course.extra,
            })}
          </p>
        </section>

        {/* два числа, а не сальдо: рост съедает резерв, удаление означает
            выкинутый материал, и «плюс три минус три» тут не ноль */}
        <section className="panel card-stat" data-card="growth">
          {course.baseline ? (
            <>
              <p className="pair">
                <b>{signed(course.baseline.added)}</b> {t('status.addedToPlan')}
              </p>
              <p className="pair">
                <b>{course.baseline.removed}</b> {t('status.droppedFromPlan')}
              </p>
              <p className="hint">
                {t('status.grown', {
                  date: shortDate(course.baseline.approved_at.slice(0, 10)),
                })}
              </p>
            </>
          ) : (
            <>
              <p className="hint">{t('status.noBaseline')}</p>
              {own && (
                <button
                  type="button"
                  className="link"
                  onClick={() => navigate('/plan')}
                >
                  {t('status.sendForApproval')}
                </button>
              )}
            </>
          )}
        </section>
      </div>

      {/* Долги по записи — хозяйство учителя, и только его: у методиста
          поля `records` в ответе нет вовсе. Число здесь кликабельно, потому
          что число, на которое нельзя нажать, заставляет искать его
          источник руками. */}
      {/* на какой доле посчитано всё остальное: дыру называем вслух, а не
          выдаём догадку за факт */}
      {course.records?.confirmed > 0 &&
        course.records.confirmed < course.records.held && (
          <p className="hint">
            {t('status.recordedShare', {
              confirmed: course.records.confirmed,
              held: course.records.held,
            })}
          </p>
        )}

      {course.records?.unclosed > 0 && (
        <p className="hint warning">
          {t('status.unclosed', { count: course.records.unclosed })}{' '}
          <button type="button" className="link" onClick={onCloseDebts}>
            {t('status.closeDebts')}
          </button>
        </p>
      )}

      {/* про год говорим отдельно: на плашку состояния это не влияет */}
      {course.last_lesson_date && course.last_lesson_date > course.year_end && (
        <p className="hint warning">
          {t('status.pastYear', {
            date: shortDate(course.last_lesson_date),
            year: shortDate(course.year_end),
          })}
        </p>
      )}

      {course.baseline?.themes.length > 0 && (
        <section className="panel">
          <h3>{t('status.grownThemes')}</h3>
          <ul className="progress-themes">
            {course.baseline.themes.map((theme) => (
              <li key={theme.title ?? 'loose'}>
                <span>{theme.title ?? t('status.looseTheme')}</span>
                <b>{signed(theme.added)}</b>
              </li>
        ))}
          </ul>
        </section>
      )}

      {course.next.length > 0 && (
        <section className="panel">
          <h3>{t('status.next')}</h3>
          <ul className="progress-next">
            {course.next.map((lesson) => (
              <li key={lesson.number}>
                <span className="when">
                  {shortDate(lesson.date)} <em>{shortWeekday(lesson.date)}</em>
                </span>
                <span className="what">{lesson.title}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

    </div>
  )


  return (
    <li className="panel" data-course={course.id}>
      <button
        type="button"
        className="progress-head"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span className="course">
          {open ? '▾' : '▸'} {course.name}
        </span>
        <span className="where">{whereText(course)}</span>
        {/* число со знаком, а не «резерв −28 уроков»: смысл минуса
            проговаривает плашка справа, и повторять его словами
            значит спорить с ней на полстроки */}
        {/* дефицит говорит словами и рядом с плашкой состояния, а
            не мелким текстом внизу: это главное, что нужно узнать */}
        {course.missing > 0 ? (
          <span className="reserve overflow">
            {t('status.overflow', { count: course.missing })}
          </span>
        ) : (
          <span className="reserve">
            {t('status.reserveLabel')}: {signed(course.reserve)}
          </span>
        )}
        <span className={`badge state ${short(course) ? 'bad' : 'good'}`}>
          {statusText(course)}
        </span>
        {mark}
      </button>

      {open && (
        <>
          {details(course)}
          {actions}
        </>
      )}
    </li>
  )
}
