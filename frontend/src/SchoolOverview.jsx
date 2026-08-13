import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { fetchSchoolOverview, renameMySchool } from './api'
import { useSchoolSection } from './School'

/**
 * What the school is made of, in numbers, and what is missing.
 *
 * One request rather than five lists: this page shows counts, and five
 * requests for five numbers is five chances to draw half a page. The
 * «what next» line at the bottom is the same idea as the dashboard's steps —
 * an empty school should say where to start rather than show four zeroes.
 */
export default function SchoolOverview() {
  const { t } = useTranslation()
  const { user, onLoggedOut, onSchoolChange } = useSchoolSection()
  const [data, setData] = useState(null)
  const [name, setName] = useState(user?.school?.name ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    fetchSchoolOverview()
      .then((result) => {
        setData(result)
        // имя берём отсюда, а не из профиля: страницу рисуют раньше, чем
        // /api/me/ ответит, и поле оставалось пустым
        setName(result.school.name)
      })
      .catch(handleError)
  }, [handleError])

  const rename = (event) => {
    event.preventDefault()
    const value = name.trim()
    if (!value || value === data.school.name || busy) return

    setBusy(true)
    setError(null)
    renameMySchool(value)
      .then((updated) => {
        // the name lives in the bar's copy of the profile too
        onSchoolChange?.(updated)
        setData((current) =>
          current ? { ...current, school: { ...current.school, name: value } } : current,
        )
      })
      .catch(handleError)
      .finally(() => setBusy(false))
  }

  if (!data) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  // the first thing that is missing, in the order the sections depend on
  // each other: a year, then somebody to teach, then something to teach
  const missing =
    (!data.year && 'year') ||
    (!data.courses && 'courses') ||
    (!data.assignments && 'assignments') ||
    (!data.master_slots && 'timetable') ||
    null

  return (
    <>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        <h3>{t('school.profile.title')}</h3>
        <form className="add-form" onSubmit={rename}>
          <input
            value={name}
            maxLength={200}
            aria-label={t('school.profile.nameLabel')}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
          />
          <button
            type="submit"
            disabled={busy || !name.trim() || name.trim() === data.school.name}
          >
            {busy ? t('common.saving') : t('common.save')}
          </button>
        </form>
      </section>

      <section className="panel">
        <h3>{t('school.overview.title')}</h3>

        <ul className="summary-cards">
          <li>
            <span className="value">{data.teachers}</span>
            <span className="label">{t('school.overview.teachers')}</span>
            <span className="hint">
              {t('school.overview.admins', { count: data.admins })}
            </span>
          </li>
          <li>
            <span className="value">{data.courses}</span>
            <span className="label">{t('school.overview.courses')}</span>
            {data.courses_without_teacher > 0 && (
              <span className="hint warning">
                {t('school.overview.withoutTeacher', {
                  count: data.courses_without_teacher,
                })}
              </span>
            )}
          </li>
          <li>
            <span className="value">{data.assignments}</span>
            <span className="label">{t('school.overview.assignments')}</span>
          </li>
          <li>
            <span className="value">{data.master_slots}</span>
            <span className="label">{t('school.overview.masterSlots')}</span>
            {data.master_slots_unassigned > 0 && (
              <span className="hint warning">
                {t('school.overview.unassigned', {
                  count: data.master_slots_unassigned,
                })}
              </span>
            )}
          </li>
        </ul>

        {missing && (
          <p className="hint next-step">{t(`school.overview.next.${missing}`)}</p>
        )}
      </section>

      <section className="panel">
        <h3>{t('school.year.title')}</h3>
        <p className="hint">
          {data.year
            ? t('school.overview.yearSet', {
                name: data.year.name,
                terms: data.year.terms,
              })
            : t('school.year.hint')}
        </p>
        <p>
          <Link to="/year">{t('school.year.action')}</Link>
        </p>
      </section>

      <section className="panel">
        <h3>{t('schoolSchedule.title')}</h3>
        <p className="hint">{t('schoolSchedule.hint')}</p>
        <p>
          <Link to="/school/schedule">{t('schoolSchedule.open')}</Link>
        </p>
      </section>
    </>
  )
}
