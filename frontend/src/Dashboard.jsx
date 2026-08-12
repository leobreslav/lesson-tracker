import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { createDemoData, wipeAllData } from './api'
import { dateRange } from './dates'

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
  const noYear = year.exists ? null : t('nav.needYear')
  const noClass = classes.count ? null : t('nav.needClass')

  return [
    {
      key: 'year',
      to: '/year',
      done: year.exists,
      summary: year.exists && `${year.name}, ${dateRange(year.start, year.end)}`,
      blocked: null,
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
      blocked: noYear,
    },
    {
      key: 'classes',
      to: '/classes',
      done: classes.count > 0,
      summary: classes.count && classes.names.join(', '),
      blocked: noYear,
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

  const removeEverything = () => {
    const confirmed = window.confirm(t('dashboard.wipe.confirm'))
    if (confirmed) run(wipeAllData)
  }

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{name ? t('dashboard.greeting', { name }) : t('app.name')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {everythingDone ? (
        <>
          <p className="hint">{t('dashboard.allDone')}</p>

          <ul className="class-summary">
            {status.classes.items.map((item) => (
              <li key={item.id} className="panel">
                <strong>{item.name}</strong>
                <span className="hint">
                  {t('dashboard.classLine', {
                    slots: item.slots,
                    past: item.past,
                    remaining: item.remaining,
                    plan: item.plan_lessons,
                  })}
                </span>
                <span
                  className={`balance ${item.balance < 0 ? 'bad' : 'good'}`}
                  title={t('dashboard.balanceHint')}
                >
                  {item.balance > 0 ? '+' : ''}
                  {item.balance}
                </span>
              </li>
            ))}
          </ul>

          <p className="hint">
            <Trans i18nKey="dashboard.more">
              <Link to="/schedule">schedule</Link>
              <Link to="/layout">layout</Link>
            </Trans>
          </p>
        </>
      ) : (
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

      <section className="panel demo-panel">
        {empty ? (
          <>
            <h3>{t('dashboard.demo.title')}</h3>
            <p className="hint">{t('dashboard.demo.hint')}</p>
            <button type="button" disabled={busy} onClick={() => run(createDemoData)}>
              {busy ? t('dashboard.demo.busy') : t('dashboard.demo.action')}
            </button>
          </>
        ) : (
          <>
            <h3>{t('dashboard.wipe.title')}</h3>
            <p className="hint">{t('dashboard.wipe.hint')}</p>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={removeEverything}
            >
              {busy ? t('dashboard.wipe.busy') : t('dashboard.wipe.action')}
            </button>
          </>
        )}
      </section>
    </main>
  )
}
