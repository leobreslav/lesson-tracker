import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import EmptyState from './EmptyState'
import {
  createSchool,
  deleteSchool,
  fetchSchools,
  inviteSchoolAdmin,
  renameSchool,
} from './api'

/**
 * Every school in the installation — the superuser's section.
 *
 * This is the only screen where being a Django superuser shows up in the
 * ordinary interface. It exists because the two things it does cannot be
 * done from inside a school: creating one, and giving a brand new school its
 * first administrator, who has nobody to be invited by yet.
 *
 * It hands out schools and nothing more. A superuser stays a plain member of
 * their own school on every other page.
 */
export default function Schools({ user, onLoggedOut }) {
  const { t } = useTranslation()
  const [schools, setSchools] = useState(null)
  const [name, setName] = useState('')
  const [editing, setEditing] = useState(null) // {id, value}
  const [inviting, setInviting] = useState(null) // {id, value}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () => fetchSchools().then(setSchools).catch(handleError),
    [handleError],
  )

  useEffect(() => {
    load()
  }, [load])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await request()
      await load()
      return result
    } catch (err) {
      handleError(err)
      return null
    } finally {
      setBusy(false)
    }
  }

  const add = (event) => {
    event.preventDefault()
    const value = name.trim()
    if (!value || busy) return
    run(() => createSchool(value)).then((created) => {
      if (created) {
        setName('')
        // a school with no administrator is a dead end, so point at the step
        setInviting({ id: created.id, value: '' })
      }
    })
  }

  const commitRename = () => {
    if (!editing) return
    const { id, value } = editing
    const previous = schools.find((item) => item.id === id)
    setEditing(null)

    const trimmed = value.trim()
    if (!trimmed || trimmed === previous.name) return
    run(() => renameSchool(id, trimmed))
  }

  const remove = (school) => {
    if (!window.confirm(t('schools.deleteConfirm', { name: school.name }))) return
    run(() => deleteSchool(school.id))
  }

  const invite = (event, school) => {
    event.preventDefault()
    const value = inviting?.value.trim()
    if (!value || busy) return

    run(() => inviteSchoolAdmin(school.id, value)).then((invitation) => {
      if (invitation) {
        setInviting(null)
        setNotice(t('schools.invited', { email: invitation.email, name: school.name }))
      }
    })
  }

  if (schools === null) {
    return (
      <main className="page narrow">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{t('schools.title')}</h1>
      </header>

      <p className="hint">{t('schools.hint')}</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="hint" role="status">
          {notice}
        </p>
      )}

      <form className="add-form" onSubmit={add}>
        <input
          value={name}
          maxLength={200}
          placeholder={t('schools.placeholder')}
          aria-label={t('schools.placeholder')}
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim()}>
          {t('schools.create')}
        </button>
      </form>

      {!schools.length && (
        <EmptyState title={t('schools.empty.title')}>{t('schools.empty.hint')}</EmptyState>
      )}

      <ul className="school-list">
        {schools.map((school) => (
          <li key={school.id} className="panel">
            <div className="school-head">
              {editing?.id === school.id ? (
                <input
                  autoFocus
                  value={editing.value}
                  maxLength={200}
                  aria-label={t('schools.newName')}
                  onChange={(event) =>
                    setEditing({ ...editing, value: event.target.value })
                  }
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') setEditing(null)
                    if (event.key === 'Enter') commitRename()
                  }}
                  onBlur={commitRename}
                />
              ) : (
                <button
                  type="button"
                  className="link name"
                  title={t('schools.rename')}
                  disabled={busy}
                  onClick={() => setEditing({ id: school.id, value: school.name })}
                >
                  {school.name}
                </button>
              )}

              {school.id === user?.school?.id && (
                <span className="badge">{t('schools.mine')}</span>
              )}

              <button
                type="button"
                className="link"
                aria-label={t('schools.delete', { name: school.name })}
                disabled={busy}
                onClick={() => remove(school)}
              >
                ✕
              </button>
            </div>

            <p className="hint">
              {t('common.memberCount', { count: school.members })}
              {school.admins.length > 0
                ? ` · ${t('schools.admins')}: ${school.admins.join(', ')}`
                : ` · ${t('schools.noAdmin')}`}
            </p>

            {inviting?.id === school.id ? (
              <form className="add-form" onSubmit={(event) => invite(event, school)}>
                <input
                  autoFocus
                  type="email"
                  value={inviting.value}
                  placeholder={t('school.people.emailPlaceholder')}
                  aria-label={t('school.people.emailPlaceholder')}
                  disabled={busy}
                  onChange={(event) =>
                    setInviting({ ...inviting, value: event.target.value })
                  }
                />
                <button type="submit" disabled={busy || !inviting.value.trim()}>
                  {t('schools.inviteAdmin')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setInviting(null)}
                >
                  {t('common.cancel')}
                </button>
              </form>
            ) : (
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setInviting({ id: school.id, value: '' })}
              >
                {t('schools.inviteAdmin')}
              </button>
            )}
          </li>
        ))}
      </ul>
    </main>
  )
}
