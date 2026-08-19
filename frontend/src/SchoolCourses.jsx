import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import EmptyState from './EmptyState'
import PersonPicker, { describePerson, matchItem } from './PersonPicker'
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
  fetchMembers,
  fetchSchoolYears,
  fetchSubjects,
  renameCourse,
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
  const [form, setForm] = useState({
    name: '',
    subject: '',
    grade: '',
    teacher: '',
    methodist: '',
  })
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

  useEffect(() => {
    Promise.all([fetchSchoolYears(), fetchSubjects(), fetchGrades(), fetchMembers()])
      .then(([yearList, subjectList, gradeList, people]) => {
        setYears(yearList)
        setYearId((current) => current ?? yearList[0]?.id ?? null)
        setSubjects(subjectList)
        setGrades(gradeList)
        setMembers(people)
      })
      .catch(handleError)
  }, [handleError])

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

  /**
   * Завести курс — и сразу назвать людей, если они уже известны.
   *
   * Учитель и методист здесь необязательны, но стоят в той же форме: курс
   * почти всегда заводят, уже зная, кто его поведёт, и отправлять человека
   * потом искать только что созданную строку в списке — лишний заход.
   *
   * Пишутся они **после** курса и отдельными запросами: это разные
   * таблицы, и у назначения свои отказы (занятый час, занятый курс).
   * Курс при этом остаётся заведённым — половина сделанного тут лучше
   * ничего, потому что видно, что именно не удалось, и поправить это
   * можно на месте, в карточке.
   */
  const add = (event) => {
    event.preventDefault()
    const name = form.name.trim()
    if (!name || !form.subject || !form.grade || busy || !namesReady) return

    const teacher = matchItem(members, form.teacher, describePerson)
    const methodist = matchItem(members, form.methodist, describePerson)

    run(async () => {
      const made = await createCourse({
        year: yearId,
        name,
        subject: Number(form.subject),
        grade: Number(form.grade),
      })

      if (teacher) await createAssignment(made.id, teacher.id)
      if (methodist) await createMethodist(made.id, methodist.id)

      setForm((current) => ({ ...current, name: '', teacher: '', methodist: '' }))
    })
  }

  /*
   * Набранное имя разрешилось в человека — или поле пусто.
   *
   * Учитель и методист тут необязательны, и молчаливый пропуск выглядел
   * так: набрал «Иванова» вместо «Мария Иванова · ivanova@…», нажал
   * «Добавить» — курс завёлся **без** ведущего, и ни слова о том, что
   * введённое выбросили. Пустое поле по-прежнему значит «не называем».
   */
  const resolved = (text) =>
    !(text ?? '').trim() || matchItem(members, text, describePerson) !== null

  const namesReady = resolved(form.teacher) && resolved(form.methodist)

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
   * Поручить курс — обычным назначением.
   *
   * Различать «учителя школы» и «приглашённого» здесь больше незачем:
   * приглашение заводит учётку сразу, и в списке они стоят рядом. Отличает
   * приглашённого только пометка «ещё не входил».
   */
  const assign = (course) => {
    const teacherId = assigning[course.id]
    if (!teacherId || busy) return

    run(() =>
      createAssignment(course.id, Number(teacherId)).then(() =>
        setAssigning((current) => ({ ...current, [course.id]: '' })),
      ),
    )
  }

  /* кого выбрали в методисты — этим же ответом живёт и кнопка рядом:
     пока она смотрела на набранный текст, а действие на найденного
     человека, «Иванов» зажигал кнопку, которая ничего не делала */
  const namedMethodist = (course) =>
    matchItem(members, naming[course.id], describePerson)

  /**
   * Назначить методиста — того, кто утверждает план этого курса.
   *
   * Та же пара «курс и человек», что у преподавания, и та же кнопка рядом:
   * вопросы разные («кто ведёт» против «кто утверждает»), но отвечают на
   * них в одном месте — на карточке курса.
   */
  const nameMethodist = (course) => {
    const person = namedMethodist(course)
    if (!person || busy) return

    run(() =>
      createMethodist(course.id, person.id).then(() =>
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
          {/* необязательные: курс почти всегда заводят, уже зная, кто его
              поведёт, и второй заход в карточку ради этого — лишний */}
          <PersonPicker
            items={members}
            value={form.teacher}
            label={t('school.courses.newTeacher')}
            placeholder={t('school.courses.newTeacher')}
            disabled={busy}
            describe={describePerson}
            onChange={(text) => setForm((current) => ({ ...current, teacher: text }))}
          />
          <PersonPicker
            items={members}
            value={form.methodist}
            label={t('school.courses.newMethodist')}
            placeholder={t('school.courses.newMethodist')}
            disabled={busy}
            describe={describePerson}
            onChange={(text) => setForm((current) => ({ ...current, methodist: text }))}
          />
          <button
            type="submit"
            disabled={
              busy || !form.name.trim() || !form.subject || !form.grade || !namesReady
            }
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
                  {/*
                    Строка раскрывается кликом по себе, а не по одной
                    стрелке в углу. Раскрытие — то, чего от строки списка
                    ждут, и целиться ради него в значок шириной в полтора
                    десятка пикселей приходилось каждый раз. А по названию
                    раньше открывалось переименование — то есть самый
                    крупный и заметный элемент строки делал не то, чего от
                    него ждут, и промах стоил открытого поля ввода.

                    Переименование уехало под карандаш, который виден при
                    наведении: правят название редко, а раскрывают строку
                    постоянно.
                  */}
                  <div className="course-head">
                    {editing?.id === course.id ? (
                      <input
                        autoFocus
                        className="course-rename"
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
                        className="course-open"
                        aria-expanded={open}
                        onClick={() => setExpanded(open ? null : course.id)}
                      >
                        <span className="toggle" aria-hidden="true">
                          {open ? '▾' : '▸'}
                        </span>
                        <span className="name">{course.name}</span>
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
                      </button>
                    )}

                    <span className="course-head-actions">
                      <button
                        type="button"
                        className="link"
                        title={t('classes.rename')}
                        aria-label={t('school.courses.renameLabel', {
                          name: course.name,
                        })}
                        disabled={busy}
                        onClick={() =>
                          setEditing({ id: course.id, value: course.name })
                        }
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        className="link"
                        aria-label={t('classes.delete', { name: course.name })}
                        disabled={busy}
                        onClick={() => remove(course)}
                      >
                        ✕
                      </button>
                    </span>
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
                          {course.teachers.length === 0 ? (
                            <span className="hint">{t('school.courses.noTeacher')}</span>
                          ) : (
                            course.teachers.map((teacher) => (
                              <span
                                className={teacher.arrived ? 'tag' : 'tag pending'}
                                key={teacher.id}
                                title={
                                  teacher.arrived
                                    ? undefined
                                    : t('school.people.waitingHint')
                                }
                              >
                                {teacher.name}
                                {teacher.arrived ? '' : ` — ${t('school.people.waiting')}`}
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
                        </div>
                        {course.teachers.length === 0 && (
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
                                <option key={person.id} value={person.id}>
                                  {fullName(person)}
                                  {person.arrived ? '' : ` — ${t('school.people.waiting')}`}
                                </option>
                              ))}
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
                          <PersonPicker
                            items={members.filter(
                              (person) =>
                                !course.methodists.some(
                                  (item) => item.id === person.id,
                                ),
                            )}
                            value={naming[course.id] ?? ''}
                            label={t('school.courses.methodistLabel', {
                              name: course.name,
                            })}
                            placeholder={t('school.courses.pickMethodist')}
                            disabled={busy}
                            describe={describePerson}
                            onChange={(text) =>
                              setNaming((current) => ({
                                ...current,
                                [course.id]: text,
                              }))
                            }
                          />
                          <button
                            type="button"
                            className="secondary"
                            aria-label={t('school.courses.methodistAction', {
                              name: course.name,
                            })}
                            disabled={busy || !namedMethodist(course)}
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
