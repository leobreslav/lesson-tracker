import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import EmptyState from './EmptyState'
import RosterDialog from './RosterDialog'
import {
  createAssignment,
  createCourse,
  createMethodist,
  deleteAssignment,
  deleteCourse,
  deleteMethodist,
  fetchAssignments,
  fetchCourses,
  fetchGrades,
  fetchInvitations,
  fetchMembers,
  fetchSchoolYears,
  fetchSubjects,
  renameCourse,
  setInvitationCourses,
} from './api'
import { useSchoolSection } from './School'

const fullName = (person) =>
  [person.first_name, person.last_name].filter(Boolean).join(' ') || person.email

/**
 * The school's courses: what exists, and who teaches each of them.
 *
 * The other end of the same assignment table the teachers tab writes to.
 * A course with nobody on it is a normal state — it is also the one worth
 * noticing, so it says so out loud.
 */
export default function SchoolCourses() {
  const { t } = useTranslation()
  const { onLoggedOut } = useSchoolSection()
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [courses, setCourses] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [grades, setGrades] = useState([])
  const [members, setMembers] = useState([])
  /*
   * Приглашённые учителя — те, кому курс можно поручить до первого входа.
   *
   * Учётки у них ещё нет, значит и назначения быть не может: курс ждёт
   * человека в самом приглашении. Список нужен целиком, а не по курсу:
   * из него выбирают в каждой карточке.
   */
  const [invited, setInvited] = useState([])
  const [form, setForm] = useState({ name: '', subject: '', grade: '' })
  const [editing, setEditing] = useState(null) // {id, value}
  const [assigning, setAssigning] = useState({}) // course id -> teacher id
  const [naming, setNaming] = useState({}) // course id -> methodist id
  const [expanded, setExpanded] = useState(null) // какой курс раскрыт
  const [roster, setRoster] = useState(null) // у какого курса открыт состав
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const loadInvited = useCallback(
    () =>
      fetchInvitations({ kind: 'teacher' }).then((list) =>
        setInvited(list.filter((item) => !item.accepted)),
      ),
    [],
  )

  useEffect(() => {
    Promise.all([
      fetchSchoolYears(),
      fetchSubjects(),
      fetchGrades(),
      fetchMembers(),
      loadInvited(),
    ])
      .then(([yearList, subjectList, gradeList, people]) => {
        setYears(yearList)
        setYearId((current) => current ?? yearList[0]?.id ?? null)
        setSubjects(subjectList)
        setGrades(gradeList)
        setMembers(people)
      })
      .catch(handleError)
  }, [handleError, loadInvited])

  const reload = useCallback(
    () =>
      yearId
        ? fetchCourses(yearId, { scope: 'school' }).then(setCourses)
        : Promise.resolve(setCourses(null)),
    [yearId],
  )

  useEffect(() => {
    reload().catch(handleError)
  }, [reload, handleError])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await reload()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const add = (event) => {
    event.preventDefault()
    const name = form.name.trim()
    if (!name || !form.subject || !form.grade || busy) return

    run(() =>
      createCourse({
        year: yearId,
        name,
        subject: Number(form.subject),
        grade: Number(form.grade),
      }).then(() => setForm((current) => ({ ...current, name: '' }))),
    )
  }

  const commitRename = () => {
    if (!editing) return
    const { id, value } = editing
    const previous = courses.find((item) => item.id === id)
    setEditing(null)

    const trimmed = value.trim()
    if (!trimmed || trimmed === previous.name) return
    run(() => renameCourse(id, trimmed))
  }

  const remove = (course) => {
    if (!window.confirm(t('school.courses.deleteConfirm', { name: course.name }))) return
    run(() => deleteCourse(course.id))
  }

  /**
   * Поручить курс — учителю школы или тому, кого только пригласили.
   *
   * Ответ на один вопрос («кто ведёт»), а таблицы разные: у вошедшего это
   * назначение, у приглашённого — курс в самом приглашении, потому что
   * учётки, на которую встало бы назначение, ещё нет. Нагрузку раздают в
   * тот же день, когда вписывают адреса, а первого входа ждут неделями, и
   * до этой правки поручить курс приглашённому было нечем вовсе.
   *
   * Что выбрали, говорит сам value: `user:12` или `invite:5`. Голые id
   * двух разных таблиц в одном селекте однажды совпали бы.
   */
  const assign = (course) => {
    const picked = assigning[course.id]
    if (!picked || busy) return

    const [kind, id] = picked.split(':')
    const done = () => setAssigning((current) => ({ ...current, [course.id]: '' }))

    if (kind === 'invite') {
      const invitation = invited.find((item) => item.id === Number(id))
      if (!invitation) return

      run(() =>
        setInvitationCourses(invitation.id, [...invitation.courses, course.id])
          .then(loadInvited)
          .then(done),
      )
      return
    }

    run(() => createAssignment(course.id, Number(id)).then(done))
  }

  /** Передумали до первого входа: курс уходит из приглашения. */
  const dropPending = (course, pending) => {
    const invitation = invited.find((item) => item.id === pending.invitation)
    if (!invitation || busy) return

    run(() =>
      setInvitationCourses(
        invitation.id,
        invitation.courses.filter((id) => id !== course.id),
      ).then(loadInvited),
    )
  }

  /**
   * Назначить методиста — того, кто утверждает план этого курса.
   *
   * Та же пара «курс и человек», что у преподавания, и та же кнопка рядом:
   * вопросы разные («кто ведёт» против «кто утверждает»), но отвечают на
   * них в одном месте — на карточке курса.
   */
  const nameMethodist = (course) => {
    const personId = naming[course.id]
    if (!personId || busy) return

    run(() =>
      createMethodist(course.id, Number(personId)).then(() =>
        setNaming((current) => ({ ...current, [course.id]: '' })),
      ),
    )
  }

  const dropMethodist = (row) => run(() => deleteMethodist(row))

  /**
   * Take a teacher off a course.
   *
   * The card knows the pair, not the row that holds it, so the row is looked
   * up first. The server then refuses while there is work behind the link,
   * and the confirmation repeats the request with `force` — nothing is
   * deleted either way, which is what the message says.
   */
  const unassign = (course, teacher) =>
    run(async () => {
      const rows = await fetchAssignments({ course: course.id, teacher: teacher.id })
      const link = rows[0]?.id
      if (!link) return

      return deleteAssignment(link).catch((err) => {
        if (err.code !== 'assignment_in_use') throw err
        if (!window.confirm(`${err.message}\n\n${t('school.teachers.keepsWork')}`)) return
        return deleteAssignment(link, { force: true })
      })
    })

  if (years === null) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  if (!years.length) {
    return (
      <EmptyState title={t('school.courses.needYear')}>
        {t('school.year.hint')}
      </EmptyState>
    )
  }

  return (
    <>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        <h3>{t('school.courses.title')}</h3>
        <p className="hint">{t('school.courses.hint')}</p>

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

        <form className="add-form" onSubmit={add}>
          <input
            value={form.name}
            maxLength={100}
            placeholder={t('school.courses.placeholder')}
            aria-label={t('school.courses.placeholder')}
            disabled={busy}
            onChange={(event) =>
              setForm((current) => ({ ...current, name: event.target.value }))
            }
          />
          <select
            value={form.subject}
            aria-label={t('library.subject')}
            disabled={busy}
            onChange={(event) =>
              setForm((current) => ({ ...current, subject: event.target.value }))
            }
          >
            <option value="">{t('school.courses.pickSubject')}</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </select>
          <select
            value={form.grade}
            aria-label={t('library.grade')}
            disabled={busy}
            onChange={(event) =>
              setForm((current) => ({ ...current, grade: event.target.value }))
            }
          >
            <option value="">{t('school.courses.pickGrade')}</option>
            {grades.map((grade) => (
              <option key={grade.id} value={grade.id}>
                {grade.name}
              </option>
            ))}
          </select>
          {/* без параллелей курс не завести, и форма молчала бы об этом */}
          {grades.length === 0 && (
            <Link className="hint" to="/school/reference">
              {t('school.courses.needGrades')}
            </Link>
          )}
          <button
            type="submit"
            disabled={busy || !form.name.trim() || !form.subject || !form.grade}
          >
            {t('common.add')}
          </button>
        </form>

        {courses === null ? (
          <p>{t('common.loading')}</p>
        ) : (
          <ul className="course-list">
            {courses.map((course) => {
              const open = expanded === course.id

              return (
                <li key={course.id} className={open ? 'course-row open' : 'course-row'}>
                  {/* свёрнутая строка: колонки фиксированной ширины, чтобы
                      семь курсов читались столбцами, а не лесенкой */}
                  <div className="course-head">
                    <button
                      type="button"
                      className="link toggle"
                      aria-expanded={open}
                      aria-label={t(open ? 'plan.collapse' : 'plan.expand')}
                      onClick={() => setExpanded(open ? null : course.id)}
                    >
                      {open ? '▾' : '▸'}
                    </button>

                    {editing?.id === course.id ? (
                      <input
                        autoFocus
                        value={editing.value}
                        maxLength={100}
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
                    )}

                    <span className="hint what">
                      {[course.subject_name, course.grade_name]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>

                    <span className="who">
                      {course.teachers.length === 0 ? (
                        <span className="hint warning">
                          {t('school.courses.noTeacher')}
                        </span>
                      ) : (
                        course.teachers.map((teacher) => teacher.name).join(', ')
                      )}
                      {course.methodists.length === 0 && (
                        <span className="hint warning">
                          {' · '}
                          {t('school.courses.noMethodist')}
                        </span>
                      )}
                    </span>

                    <button
                      type="button"
                      className="link"
                      aria-label={t('classes.delete', { name: course.name })}
                      disabled={busy}
                      onClick={() => remove(course)}
                    >
                      ✕
                    </button>
                  </div>

                  {open && (
                    <div className="course-body">
                      {/* две роли курса, и формы у них одинаковые: вопросы
                          разные, а действие одно — назвать человека */}
                      {/* ведущий у курса один: пока он есть, формы выбора
                          нет вовсе — иначе она обещала бы то, чего сервер
                          не сделает */}
                      <div className="course-role">
                        <span className="hint">{t('school.courses.teaches')}</span>
                        <div className="row courses">
                          {course.teachers.length === 0 &&
                          course.pending_teachers.length === 0 ? (
                            <span className="hint">{t('school.courses.noTeacher')}</span>
                          ) : (
                            course.teachers.map((teacher) => (
                              <span className="tag" key={teacher.id}>
                                {teacher.name}
                                <button
                                  type="button"
                                  className="link"
                                  aria-label={t('school.courses.unassign', {
                                    name: teacher.name,
                                  })}
                                  disabled={busy}
                                  onClick={() => unassign(course, teacher)}
                                >
                                  ✕
                                </button>
                              </span>
                            ))
                          )}
                          {/* приглашённый: место занято, но пока обещанием —
                              плашка бледнее и подписана ожиданием */}
                          {course.pending_teachers.map((pending) => (
                            <span
                              className="tag pending"
                              key={pending.invitation}
                              title={t('school.courses.pendingHint', {
                                email: pending.email,
                              })}
                            >
                              {t('school.courses.pendingName', { name: pending.name })}
                              <button
                                type="button"
                                className="link"
                                aria-label={t('school.courses.unassign', {
                                  name: pending.name,
                                })}
                                disabled={busy}
                                onClick={() => dropPending(course, pending)}
                              >
                                ✕
                              </button>
                            </span>
                          ))}
                        </div>
                        {course.teachers.length === 0 &&
                          course.pending_teachers.length === 0 && (
                          <div className="row">
                            <select
                              value={assigning[course.id] ?? ''}
                              aria-label={t('school.courses.assignLabel', {
                                name: course.name,
                              })}
                              disabled={busy}
                              onChange={(event) =>
                                setAssigning((current) => ({
                                  ...current,
                                  [course.id]: event.target.value,
                                }))
                              }
                            >
                                <option value="">{t('school.courses.pickTeacher')}</option>
                              {members.map((person) => (
                                <option key={person.id} value={`user:${person.id}`}>
                                  {fullName(person)}
                                </option>
                              ))}
                              {/* приглашённые — отдельной группой: это не
                                  «ещё один учитель», а обещание, и человек
                                  должен видеть, что курс достанется ему не
                                  сейчас, а в первый его вход */}
                              {invited.length > 0 && (
                                <optgroup label={t('school.courses.invitedGroup')}>
                                  {invited.map((item) => (
                                    <option key={item.id} value={`invite:${item.id}`}>
                                      {item.name || item.email}
                                    </option>
                                  ))}
                                </optgroup>
                              )}
                            </select>
                            {/* подпись у обеих ролей одна — «Назначить»:
                                вопросы разные, а действие одно, и колонка
                                над кнопкой уже сказала, о ком речь. Читалке
                                этого мало, поэтому у каждой свой aria-label */}
                            <button
                              type="button"
                              className="secondary"
                              aria-label={t('school.courses.assignAction', {
                                name: course.name,
                              })}
                              disabled={busy || !assigning[course.id]}
                              onClick={() => assign(course)}
                            >
                              {t('school.teachers.assign')}
                            </button>
                          </div>
                        )}
                      </div>

                      <div className="course-role">
                        <span className="hint">{t('school.courses.methodist')}</span>
                        <div className="row courses">
                          {course.methodists.length === 0 ? (
                            <span className="hint">
                              {t('school.courses.noMethodist')}
                            </span>
                          ) : (
                            course.methodists.map((person) => (
                              <span className="tag" key={person.row}>
                                {person.name}
                                <button
                                  type="button"
                                  className="link"
                                  aria-label={t('school.courses.dropMethodist', {
                                    name: person.name,
                                  })}
                                  disabled={busy}
                                  onClick={() => dropMethodist(person.row)}
                                >
                                  ✕
                                </button>
                              </span>
                            ))
                          )}
                        </div>
                        <div className="row">
                          <select
                            value={naming[course.id] ?? ''}
                            aria-label={t('school.courses.methodistLabel', {
                              name: course.name,
                            })}
                            disabled={busy}
                            onChange={(event) =>
                              setNaming((current) => ({
                                ...current,
                                [course.id]: event.target.value,
                              }))
                            }
                          >
                            <option value="">
                              {t('school.courses.pickMethodist')}
                            </option>
                            {members
                              .filter(
                                (person) =>
                                  !course.methodists.some(
                                    (item) => item.id === person.id,
                                  ),
                              )
                              .map((person) => (
                                <option key={person.id} value={person.id}>
                                  {fullName(person)}
                                </option>
                              ))}
                          </select>
                          <button
                            type="button"
                            className="secondary"
                            aria-label={t('school.courses.methodistAction', {
                              name: course.name,
                            })}
                            disabled={busy || !naming[course.id]}
                            onClick={() => nameMethodist(course)}
                          >
                            {t('school.courses.nameMethodist')}
                          </button>
                        </div>
                      </div>

                      {/* третья роль устроена так же, как две первых:
                          подпись, состояние, действие — тремя строками.
                          Пока счёт стоял в одной строке с кнопкой, он
                          прижимался к её нижнему краю, а сама кнопка
                          оказывалась строкой выше соседних */}
                      <div className="course-role">
                        <span className="hint">{t('school.courses.students')}</span>
                        <div className="row courses">
                          <span className="hint">
                            {course.students === 0
                              ? t('school.courses.noStudents')
                              : t('school.courses.studentCount', {
                                  count: course.students,
                                })}
                          </span>
                        </div>
                        <div className="row">
                          <button
                            type="button"
                            className="secondary"
                            disabled={busy}
                            onClick={() => setRoster(course)}
                          >
                            {t('school.courses.openRoster')}
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {roster && (
        <RosterDialog
          course={roster}
          onClose={() => setRoster(null)}
          onChanged={() => reload().catch(handleError)}
        />
      )}
    </>
  )
}
