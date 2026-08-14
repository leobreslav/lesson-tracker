import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  createAssignment,
  createInvitation,
  deleteAssignment,
  deleteInvitation,
  detachMember,
  fetchCourses,
  fetchInvitations,
  fetchMembers,
  setMemberRole,
} from './api'
import { useSchoolSection } from './School'

const fullName = (person) =>
  [person.first_name, person.last_name].filter(Boolean).join(' ') || person.email

/**
 * The people of the school, and what each of them teaches.
 *
 * Two lists, not one: somebody who has signed in is a member with a role and
 * a load, somebody who has only been written down is an invitation that can
 * be withdrawn. They used to share a section and reading it meant working
 * out which was which.
 *
 * Assigning a course is offered here **and** on the course card. Same table,
 * two ways in: which one somebody reaches for depends on whether they are
 * thinking about a person or about a course.
 */
export default function SchoolTeachers() {
  const { t } = useTranslation()
  const { onLoggedOut } = useSchoolSection()
  const [members, setMembers] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [courses, setCourses] = useState([])
  const [email, setEmail] = useState('')
  const [inviteAdmin, setInviteAdmin] = useState(false)
  const [assigning, setAssigning] = useState({}) // teacher id -> course id
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () =>
      Promise.all([
        fetchMembers(),
        // только учительские: ученики приглашаются составом курса, и в
        // разделе про сотрудников им делать нечего
        fetchInvitations({ kind: 'teacher' }),
        fetchCourses(null, { scope: 'school' }),
      ])
        .then(([people, invited, all]) => {
          setMembers(people)
          setInvitations(invited)
          setCourses(all)
        })
        .catch(handleError),
    [handleError],
  )

  useEffect(() => {
    load()
  }, [load])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const invite = (event) => {
    event.preventDefault()
    const value = email.trim()
    if (!value || busy) return

    run(() =>
      createInvitation({ email: value, is_school_admin: inviteAdmin }).then(() => {
        setEmail('')
        setInviteAdmin(false)
      }),
    )
  }

  const assign = (member) => {
    const courseId = assigning[member.id]
    if (!courseId || busy) return

    run(() =>
      createAssignment(Number(courseId), member.id).then(() =>
        setAssigning((current) => ({ ...current, [member.id]: '' })),
      ),
    )
  }

  /**
   * Remove a course from somebody.
   *
   * The server refuses the first time and says what is behind the link; the
   * confirmation repeats the request with `force`. Nothing is deleted either
   * way — the lessons and the plan stay, which is what the message says.
   */
  const unassign = (course) =>
    run(() =>
      deleteAssignment(course.assignment).catch((err) => {
        if (err.code !== 'assignment_in_use') throw err
        if (!window.confirm(`${err.message}\n\n${t('school.teachers.keepsWork')}`)) return
        return deleteAssignment(course.assignment, { force: true })
      }),
    )

  const detach = (member) =>
    run(() =>
      detachMember(member.id).catch((err) => {
        if (err.code !== 'member_in_use') throw err
        if (!window.confirm(`${err.message}\n\n${t('school.teachers.detachKeeps')}`)) return
        return detachMember(member.id, { force: true })
      }),
    )

  if (members === null) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  return (
    <>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        <h3>{t('school.teachers.title')}</h3>
        <p className="hint">{t('school.teachers.hint')}</p>

        <ul className="people-list">
          {members.map((member) => (
            <li key={member.id}>
              <div className="row">
                <span className="name">{fullName(member)}</span>
                <span className="hint">{member.email}</span>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={member.is_school_admin}
                    disabled={busy}
                    onChange={() =>
                      run(() => setMemberRole(member.id, !member.is_school_admin))
                    }
                  />
                  {t('school.people.admin')}
                </label>
                <button
                  type="button"
                  className="link detach"
                  disabled={busy}
                  onClick={() => detach(member)}
                >
                  {t('school.teachers.detach')}
                </button>
              </div>

              <div className="row courses">
                {member.courses.length === 0 ? (
                  <span className="hint">{t('school.teachers.noCourses')}</span>
                ) : (
                  member.courses.map((course) => (
                    <span className="tag" key={course.assignment}>
                      {course.name}
                      <button
                        type="button"
                        className="link"
                        aria-label={t('school.teachers.unassign', { name: course.name })}
                        disabled={busy}
                        onClick={() => unassign(course)}
                      >
                        ✕
                      </button>
                    </span>
                  ))
                )}
              </div>

              <div className="row">
                <select
                  value={assigning[member.id] ?? ''}
                  aria-label={t('school.teachers.assignLabel', {
                    name: fullName(member),
                  })}
                  disabled={busy}
                  onChange={(event) =>
                    setAssigning((current) => ({
                      ...current,
                      [member.id]: event.target.value,
                    }))
                  }
                >
                  <option value="">{t('school.teachers.pickCourse')}</option>
                  {courses
                    .filter(
                      (course) =>
                        !member.courses.some((mine) => mine.id === course.id),
                    )
                    .map((course) => (
                      <option key={course.id} value={course.id}>
                        {course.name}
                      </option>
                    ))}
                </select>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || !assigning[member.id]}
                  onClick={() => assign(member)}
                >
                  {t('school.teachers.assign')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h3>{t('school.invitations.title')}</h3>
        <p className="hint">{t('school.invitations.hint')}</p>

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

        {invitations.filter((item) => !item.accepted).length === 0 ? (
          <p className="hint">{t('school.invitations.none')}</p>
        ) : (
          <ul className="class-list">
            {invitations
              .filter((item) => !item.accepted)
              .map((invitation) => (
                <li key={invitation.id}>
                  <span className="name">{invitation.email}</span>
                  <span className="hint">
                    {t('school.people.pending')}
                    {invitation.is_school_admin && ` · ${t('school.people.admin')}`}
                    {/* приглашение, которое уже не сработает: человек успел
                        войти и оказаться в другой школе */}
                    {invitation.conflict && (
                      <span className="warning">
                        {' · '}
                        {t(`roster.conflict.${invitation.conflict}`, {
                          defaultValue: t(`errors.${invitation.conflict}`, {
                            email: invitation.email,
                          }),
                        })}
                      </span>
                    )}
                  </span>
                  <button
                    type="button"
                    className="link"
                    aria-label={t('school.people.withdraw')}
                    disabled={busy}
                    onClick={() => run(() => deleteInvitation(invitation.id))}
                  >
                    ✕
                  </button>
                </li>
              ))}
          </ul>
        )}
      </section>
    </>
  )
}
