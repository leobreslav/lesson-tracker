import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  createAssignment,
  createInvitation,
  deleteAssignment,
  detachMember,
  fetchCourses,
  fetchMembers,
  setMemberRole,
} from './api'
import PersonPicker, { matchItem } from './PersonPicker'
import { useSchoolSection } from './School'

const fullName = (person) =>
  [person.first_name, person.last_name].filter(Boolean).join(' ') || person.email

/**
 * Люди школы и то, что каждый из них ведёт.
 *
 * **Список один.** Их было два — участники и приглашения, — и это было
 * верно ровно до тех пор, пока приглашение оставалось записанным адресом.
 * Теперь оно заводит учётку, и приглашённый стоит в общем списке с
 * пометкой «ещё не входил»: вторая панель показывала тех же самых людей
 * второй раз, а её крестик «отозвать приглашение» удалял билет и оставлял
 * человека в школе — то есть делал не то, что обещал.
 *
 * Отвязка теперь одна на всех, в строке человека, и означает ровно то, что
 * написано.
 *
 * Назначение курса предлагается здесь **и** на карточке курса. Таблица
 * одна, дверей две: к какой потянутся, зависит от того, о чём человек
 * думает — о людях или о курсах. Обе двери при этом обязаны быть одинаково
 * честными: занятый курс не предлагается ни там, ни там.
 */
export default function SchoolTeachers() {
  const { t } = useTranslation()
  const { onLoggedOut } = useSchoolSection()
  const [members, setMembers] = useState(null)
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
        fetchCourses(null, { scope: 'school' }),
      ])
        .then(([people, all]) => {
          setMembers(people)
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
    const picked = matchItem(free, assigning[member.id], (course) => course.name)
    const courseId = picked?.id
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

  /*
   * Свободные курсы — те, у которых ведущего нет.
   *
   * Считается по самому списку курсов: у школьного ответа есть `teachers`,
   * и второй запрос ради этого не нужен.
   */
  const free = courses.filter((course) => (course.teachers ?? []).length === 0)

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

        {/*
          Форма стоит здесь, а не в своей панели.

          Панель «Приглашены» была отдельной, потому что приглашение было
          отдельной сущностью: адрес, который ждёт. Оно перестало ею быть —
          теперь это человек, который появляется в списке ниже сразу же, —
          и держать ради одной формы вторую панель с собственным
          заголовком значит спрашивать «а чем те люди отличаются от этих».
          Ничем.
        */}
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
                {/*
                  Предлагаются только **свободные** курсы.

                  Ведущий у курса один, и раньше отсюда можно было выбрать
                  занятый: сервер отвечал `course_teacher_taken`, то есть
                  форма предлагала действие, которого не сделает. На
                  карточке курса это починили, когда правило вводили, а
                  здесь забыли — две двери в одну комнату разошлись молча.

                  Передать курс от одного другому отсюда теперь нельзя, и
                  это правильно: отобрать у человека год работы мимоходом
                  из выпадающего списка не стоит. Снимают крестиком, потом
                  назначают.
                */}
                <PersonPicker
                  items={free}
                  value={assigning[member.id] ?? ''}
                  label={t('school.teachers.assignLabel', {
                    name: fullName(member),
                  })}
                  placeholder={t('school.teachers.pickCourse')}
                  disabled={busy || free.length === 0}
                  describe={(course) => course.name}
                  onChange={(text) =>
                    setAssigning((current) => ({ ...current, [member.id]: text }))
                  }
                />
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

    </>
  )
}
