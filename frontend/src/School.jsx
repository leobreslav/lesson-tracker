import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import EmptyState from './EmptyState'
import {
  createCourse,
  createInvitation,
  createSubject,
  deleteCourse,
  deleteInvitation,
  fetchCourses,
  fetchInvitations,
  fetchMembers,
  fetchSchoolYears,
  fetchSubjects,
  renameCourse,
  renameMySchool,
  setMemberRole,
} from './api'

/**
 * The administrator's section: the courses and the people.
 *
 * Both are the school's, not anyone's personally, which is why they live in
 * one place and behind one role. The calendar belongs here too by nature, but
 * it is a whole screen of its own — this page links to it instead of copying
 * it.
 */
export default function School({ user, onLoggedOut, onSchoolChange }) {
  const { t } = useTranslation()
  const [schoolName, setSchoolName] = useState(user?.school?.name ?? '')
  const [renaming, setRenaming] = useState(false)
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [courses, setCourses] = useState(null)
  const [members, setMembers] = useState([])
  const [invitations, setInvitations] = useState([])
  const [name, setName] = useState('')
  // a course now carries a subject and a grade: that is what the library
  // searches by, and the name keeps only the letter («9Б»)
  const [subjects, setSubjects] = useState([])
  const [subjectId, setSubjectId] = useState('')
  const [grade, setGrade] = useState('')
  const [newSubject, setNewSubject] = useState('')
  const [email, setEmail] = useState('')
  const [inviteAdmin, setInviteAdmin] = useState(false)
  const [editing, setEditing] = useState(null) // {id, value}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const loadPeople = useCallback(() => {
    Promise.all([fetchMembers(), fetchInvitations()])
      .then(([people, invited]) => {
        setMembers(people)
        setInvitations(invited)
      })
      .catch(handleError)
  }, [handleError])

  useEffect(() => {
    fetchSchoolYears()
      .then((list) => {
        setYears(list)
        setYearId((current) => current ?? list[0]?.id ?? null)
      })
      .catch(handleError)
    fetchSubjects()
      .then((list) => {
        setSubjects(list)
        setSubjectId((current) => current || list[0]?.id || '')
      })
      .catch(handleError)
    loadPeople()
  }, [handleError, loadPeople])

  useEffect(() => {
    if (!yearId) {
      setCourses(null)
      return
    }
    fetchCourses(yearId).then(setCourses).catch(handleError)
  }, [yearId, handleError])

  /** Run a change, then re-read what it touched. */
  const run = async (request, after) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await after()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const reloadCourses = () => fetchCourses(yearId).then(setCourses)

  const addCourse = (event) => {
    event.preventDefault()
    const value = name.trim()
    if (!value || !subjectId || !grade || busy) return

    run(
      () =>
        createCourse({
          year: yearId,
          name: value,
          subject: subjectId,
          grade: Number(grade),
        }),
      reloadCourses,
    ).then(() => setName(''))
  }

  /** A subject that is not in the list yet: added without leaving the form. */
  const addSubject = () => {
    const value = newSubject.trim()
    if (!value || busy) return

    run(
      () => createSubject(value).then((created) => setSubjectId(created.id)),
      () => fetchSubjects().then(setSubjects),
    ).then(() => setNewSubject(''))
  }

  const commitRename = () => {
    if (!editing) return
    const { id, value } = editing
    const previous = courses.find((item) => item.id === id)
    setEditing(null)

    const trimmed = value.trim()
    if (!trimmed || trimmed === previous.name) return
    run(() => renameCourse(id, trimmed), reloadCourses)
  }

  const removeCourse = (course) => {
    if (!window.confirm(t('school.courses.deleteConfirm', { name: course.name }))) return
    run(() => deleteCourse(course.id), reloadCourses)
  }

  const invite = (event) => {
    event.preventDefault()
    const value = email.trim()
    if (!value || busy) return

    run(
      () => createInvitation({ email: value, is_school_admin: inviteAdmin }),
      async () => {
        setEmail('')
        setInviteAdmin(false)
        loadPeople()
      },
    )
  }

  const toggleRole = (member) =>
    run(() => setMemberRole(member.id, !member.is_school_admin), async () => loadPeople())

  const withdraw = (invitation) =>
    run(() => deleteInvitation(invitation.id), async () => loadPeople())

  const fullName = (member) =>
    [member.first_name, member.last_name].filter(Boolean).join(' ') || member.email

  if (years === null) {
    return (
      <main className="page narrow">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{t('school.title', { name: user?.school?.name ?? '' })}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        <h3>{t('school.profile.title')}</h3>
        <form
          className="add-form"
          onSubmit={(event) => {
            event.preventDefault()
            const value = schoolName.trim()
            if (!value || value === user?.school?.name) return
            setRenaming(true)
            renameMySchool(value)
              .then((updated) => {
                // the name lives in the bar's copy of the profile too
                onSchoolChange?.(updated)
                setError(null)
              })
              .catch(handleError)
              .finally(() => setRenaming(false))
          }}
        >
          <input
            value={schoolName}
            maxLength={200}
            aria-label={t('school.profile.nameLabel')}
            disabled={renaming}
            onChange={(event) => setSchoolName(event.target.value)}
          />
          <button
            type="submit"
            disabled={
              renaming || !schoolName.trim() || schoolName.trim() === user?.school?.name
            }
          >
            {renaming ? t('common.saving') : t('common.save')}
          </button>
        </form>
      </section>

      <section className="panel">
        <h3>{t('school.year.title')}</h3>
        <p className="hint">{t('school.year.hint')}</p>
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

      <section className="panel">
        <h3>{t('school.courses.title')}</h3>
        <p className="hint">{t('school.courses.hint')}</p>

        {!years.length ? (
          <EmptyState title={t('school.courses.needYear')}>
            {t('school.year.hint')}
          </EmptyState>
        ) : (
          <>
            <div className="year-picker">
              {years.map((year) => (
                <button
                  type="button"
                  key={year.id}
                  className={year.id === yearId ? 'chip active' : 'chip'}
                  onClick={() => setYearId(year.id)}
                >
                  {year.name}
                </button>
              ))}
            </div>

            <form className="add-form" onSubmit={addCourse}>
              <input
                value={name}
                maxLength={20}
                placeholder={t('school.courses.placeholder')}
                aria-label={t('school.courses.placeholder')}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
              />
              <select
                value={subjectId}
                aria-label={t('library.subject')}
                disabled={busy}
                onChange={(event) => setSubjectId(Number(event.target.value))}
              >
                <option value="">{t('school.courses.pickSubject')}</option>
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.name}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                max={11}
                value={grade}
                placeholder={t('school.courses.gradePlaceholder')}
                aria-label={t('library.grade')}
                disabled={busy}
                onChange={(event) => setGrade(event.target.value)}
              />
              <button type="submit" disabled={busy || !name.trim() || !subjectId || !grade}>
                {t('common.add')}
              </button>
            </form>

            <div className="add-form">
              <input
                value={newSubject}
                maxLength={100}
                placeholder={t('school.courses.newSubject')}
                aria-label={t('school.courses.newSubject')}
                disabled={busy}
                onChange={(event) => setNewSubject(event.target.value)}
              />
              <button
                type="button"
                className="secondary"
                disabled={busy || !newSubject.trim()}
                onClick={addSubject}
              >
                {t('school.courses.addSubject')}
              </button>
            </div>

            {courses === null ? (
              <p>{t('common.loading')}</p>
            ) : (
              <ul className="class-list">
                {courses.map((course) => (
                  <li key={course.id}>
                    {editing?.id === course.id ? (
                      <input
                        autoFocus
                        value={editing.value}
                        maxLength={20}
                        aria-label={t('classes.newNameLabel')}
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
                      <>
                        <button
                          type="button"
                          className="link name"
                          title={t('classes.rename')}
                          disabled={busy}
                          onClick={() =>
                            setEditing({ id: course.id, value: course.name })
                          }
                        >
                          {course.name}
                        </button>
                        {course.subject_name && (
                          <span className="hint">
                            {course.subject_name}
                            {course.grade ? `, ${course.grade}` : ''}
                          </span>
                        )}
                      </>
                    )}
                    <button
                      type="button"
                      className="link"
                      aria-label={t('classes.delete', { name: course.name })}
                      disabled={busy}
                      onClick={() => removeCourse(course)}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <h3>{t('school.people.title')}</h3>
        <p className="hint">{t('school.people.hint')}</p>

        <ul className="class-list">
          {members.map((member) => (
            <li key={member.id}>
              <span className="name">{fullName(member)}</span>
              <span className="hint">{member.email}</span>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={member.is_school_admin}
                  disabled={busy}
                  onChange={() => toggleRole(member)}
                />
                {t('school.people.admin')}
              </label>
            </li>
          ))}
        </ul>

        <form className="add-form" onSubmit={invite}>
          <input
            type="email"
            value={email}
            placeholder={t('school.people.emailPlaceholder')}
            aria-label={t('school.people.emailPlaceholder')}
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label className="checkbox">
            <input
              type="checkbox"
              checked={inviteAdmin}
              disabled={busy}
              onChange={(event) => setInviteAdmin(event.target.checked)}
            />
            {t('school.people.inviteAsAdmin')}
          </label>
          <button type="submit" disabled={busy || !email.trim()}>
            {t('school.people.invite')}
          </button>
        </form>

        {invitations.length > 0 && (
          <>
            <p className="hint">{t('school.people.invited')}</p>
            <ul className="class-list">
              {invitations.map((invitation) => (
                <li key={invitation.id}>
                  <span className="name">{invitation.email}</span>
                  <span className="hint">
                    {invitation.accepted
                      ? t('school.people.accepted')
                      : t('school.people.pending')}
                    {invitation.is_school_admin && ` · ${t('school.people.admin')}`}
                  </span>
                  {!invitation.accepted && (
                    <button
                      type="button"
                      className="link"
                      aria-label={t('school.people.withdraw')}
                      disabled={busy}
                      onClick={() => withdraw(invitation)}
                    >
                      ✕
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </main>
  )
}
