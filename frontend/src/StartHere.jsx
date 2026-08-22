import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { createDemoData } from './api'
import { dateRange } from './dates'

function buildSteps(status, t) {
  const { year, calendar, classes, schedule, plan } = status
  const admin = status.is_school_admin
  const noYear = year.exists ? null : t('nav.needYear')
  const noClass = classes.count ? null : t('nav.needClass')
  // the first three steps are the school's, so a teacher only watches them:
  // no action button that would answer 403 anyway
  const forAdmin = admin ? null : t('dashboard.adminDoes')

  return [
    {
      key: 'year',
      to: admin ? '/school' : '/year',
      done: year.exists,
      summary: year.exists && `${year.name}, ${dateRange(year.start, year.end)}`,
      blocked: year.exists ? null : forAdmin,
    },
    {
      key: 'calendar',
      to: '/year',
      done: calendar.terms > 0 || calendar.exceptions > 0,
      summary:
        (calendar.terms || calendar.exceptions) &&
        t('dashboard.steps.calendar.summary', {
          terms: t('common.termCount', { count: calendar.terms }),
          breaks: t('common.breakCount', { count: calendar.exceptions }),
        }),
      blocked: noYear ?? forAdmin,
    },
    {
      key: 'classes',
      // курсы заводит администратор, поэтому и смотреть их идут туда же:
      // своего экрана со списком курсов у учителя больше нет
      to: '/school/courses',
      done: classes.count > 0,
      summary: classes.count && classes.names.join(', '),
      blocked: noYear ?? forAdmin,
    },
    {
      key: 'schedule',
      to: '/schedule',
      done: schedule.slots > 0,
      summary:
        schedule.slots && t('common.lessonCount', { count: schedule.slots }),
      blocked: noClass,
    },
    {
      key: 'plan',
      to: '/plan',
      done: plan.classes_with_plan > 0,
      summary:
        plan.classes_with_plan &&
        t('dashboard.steps.plan.summary', {
          withPlan: plan.classes_with_plan,
          total: plan.total_classes,
        }),
      blocked: noClass,
    },
  ]
}

/**
 * Есть ли что настраивать — то же условие, по которому шаги рисуются.
 *
 * Нужно оно снаружи: корень приложения показывает шаги, пока они есть, и
 * уводит на расписание, когда всё готово. Спрашивать это вторым правилом
 * значило бы завести корень, который показывает пустоту.
 */
export function hasSteps(status) {
  if (!status?.school) return false
  return !buildSteps(status, (key) => key).every((step) => step.done)
}

/**
 * Шаги первого входа — на корне приложения, и только там.
 *
 * Жили они на «Моих курсах», и вместе с тем разделом уезжать им было некуда:
 * это карта для того, у кого ещё ничего не заведено. Какое-то время они
 * стояли прямо в «Моём расписании» — корень вёл туда, — и это было
 * ошибкой: расписание открывают каждый день и ради сетки, а карта первого
 * входа отвечает на вопрос, который задают один раз. Полтора экрана поверх
 * рабочей страницы читались как реклама.
 *
 * Показываются, **пока есть что настраивать**: пройденные повторяли бы то,
 * что и так видно на самой странице. Когда настраивать нечего, корень
 * уводит на расписание, и страницы этой не существует вовсе.
 */
export default function StartHere({ status, onStatusChange, onLoggedOut }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!status?.school) return null

  const steps = buildSteps(status, t)
  const nextIndex = steps.findIndex((step) => !step.done && !step.blocked)
  if (steps.every((step) => step.done)) return null

  const empty = steps.every((step) => !step.done)

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      const result = await request()
      onStatusChange(result.status)
    } catch (err) {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="start-here">
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <p className="hint">{t('dashboard.intro')}</p>

      <ol className="steps">
        {steps.map((step, index) => (
          <li
            key={step.key}
            className={
              'step' +
              (step.done ? ' done' : '') +
              (step.blocked ? ' blocked' : '') +
              (index === nextIndex ? ' next' : '')
            }
          >
            <span className="step-mark" aria-hidden="true">
              {step.done ? '✓' : index + 1}
            </span>

            <span className="step-body">
              {step.blocked ? (
                <strong>{t(`dashboard.steps.${step.key}.title`)}</strong>
              ) : (
                <Link to={step.to}>
                  <strong>{t(`dashboard.steps.${step.key}.title`)}</strong>
                </Link>
              )}
              <span className="hint">
                {step.blocked ||
                  step.summary ||
                  t(`dashboard.steps.${step.key}.missing`)}
              </span>
            </span>

            {!step.done && !step.blocked && (
              <Link className="step-action" to={step.to}>
                {t(`dashboard.steps.${step.key}.action`)}
              </Link>
            )}
          </li>
        ))}
      </ol>

      {/* демо заводит год и курсы, а они школьные — отсюда роль. Кнопка
          показывается только пустому аккаунту: дальше есть что читать, и
          предлагать «посмотреть пример» поверх своих данных незачем.
          Обратной кнопки нет — снос всего заведённого одним нажатием стоил
          дороже, чем разовое удобство */}
      {status.is_school_admin && empty && (
        <section className="panel">
          <h3>{t('dashboard.demo.title')}</h3>
          <p className="hint">{t('dashboard.demo.hint')}</p>
          <button type="button" disabled={busy} onClick={() => run(createDemoData)}>
            {busy ? t('dashboard.demo.busy') : t('dashboard.demo.action')}
          </button>
        </section>
      )}
    </section>
  )
}
