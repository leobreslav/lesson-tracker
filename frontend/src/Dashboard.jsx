import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import CourseStatus from './CourseStatus'
import { createDemoData } from './api'
import { dateRange } from './dates'

/**
 * Главная: как идут курсы, а до того — с чего начать.
 *
 * Раньше это были две страницы. «Состояние курсов» отвечало на первый
 * вопрос дня — где я и успеваю ли, — но заходить туда приходилось нарочно,
 * а главная встречала списком классов с одним числом в строке: те же
 * данные, только беднее. Теперь состояние курсов и есть главная, а шаги
 * первого входа живут над ним, пока не пройдены.
 */

/**
 * The steps of a first visit.
 *
 * The sections depend on each other: year → markup → classes → schedule →
 * plan. There is no wizard forcing the order — there is an honest map: what
 * is done, what comes next and why the rest is not usable yet.
 *
 * Each step carries only its data; the wording comes from the dictionary by
 * the step key, so a step is one entry here and one block in the locale file.
 */
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

export default function Dashboard({ user, status, onStatusChange, onLoggedOut }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!user || !status) {
    return (
      <main className="card">
        <p>{t('common.loading')}</p>
      </main>
    )
  }

  const name = [user.first_name, user.last_name].filter(Boolean).join(' ')

  // only a superuser gets this far without a school: everybody else is sent
  // to the NoSchool screen before the router runs
  if (!status.school) {
    return (
      <main className="page narrow">
        <header className="page-header">
          <h1>{t('noSchool.title')}</h1>
        </header>
        <section className="panel">
          <p className="hint">{t('noSchool.superuser')}</p>
          <p>
            <Link to="/schools">{t('nav.schools')}</Link>
          </p>
        </section>
      </main>
    )
  }

  const steps = buildSteps(status, t)
  const nextIndex = steps.findIndex((step) => !step.done && !step.blocked)
  const everythingDone = steps.every((step) => step.done)
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
    <main className="page">
      <header className="page-header">
        <h1>{name ? t('dashboard.greeting', { name }) : t('app.name')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {/* шаги показываются, пока есть что настраивать: пройденные они
          повторяли бы то, что и так видно в состоянии курсов ниже */}
      {!everythingDone && (
        <>
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
        </>
      )}

      <CourseStatus onLoggedOut={onLoggedOut} />

      {/* демо заводит год и курсы, а они школьные — отсюда роль. Кнопка
          показывается только пустому аккаунту: дальше на главной есть что
          читать, и предлагать «посмотреть пример» поверх своих данных
          незачем. Обратной кнопки нет — снос всего заведённого одним
          нажатием стоил дороже, чем разовое удобство: демо разбирается
          теми же экранами, что и настоящие данные */}
      {status.is_school_admin && empty && (
        <section className="panel">
          <h3>{t('dashboard.demo.title')}</h3>
          <p className="hint">{t('dashboard.demo.hint')}</p>
          <button type="button" disabled={busy} onClick={() => run(createDemoData)}>
            {busy ? t('dashboard.demo.busy') : t('dashboard.demo.action')}
          </button>
        </section>
      )}
    </main>
  )
}
