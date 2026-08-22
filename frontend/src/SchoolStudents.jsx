import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import EmptyState from './EmptyState'
import { detachMember, fetchMembers } from './api'
import { useSchoolSection } from './School'

const fullName = (person) =>
  [person.first_name, person.last_name].filter(Boolean).join(' ') || person.email

/**
 * Ученики школы — все, а не по курсу.
 *
 * Состав курса набирают в карточке курса, и до этой вкладки человек виден
 * был только оттуда. Двух вещей поэтому нельзя было сделать вовсе: найти
 * ученика, не помня, в каком он курсе, и **отвязать его от школы** —
 * ошиблись адресом при вставке, и исправить это из интерфейса нечем.
 *
 * Зачисления показаны рядом с именем и снятые тоже, приглушённо: «он у нас
 * есть, но нигде не учится» и «он учился вот здесь» — разные ответы, и оба
 * нужны, когда ищешь, кого отвязывать.
 */
export default function SchoolStudents() {
  const { t } = useTranslation()
  const { onLoggedOut } = useSchoolSection()
  const [students, setStudents] = useState(null)
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
    () => fetchMembers({ kind: 'student' }).then(setStudents),
    [],
  )

  useEffect(() => {
    load().catch(handleError)
  }, [load, handleError])

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

  /**
   * Отвязать от школы: сперва отказ со счётчиком, потом подтверждение.
   *
   * Тот же разговор, что с учителем, и та же правда в конце: ничего не
   * удаляется — ученик снимается с курсов, а сделанное им остаётся.
   */
  const detach = (student) =>
    run(() =>
      detachMember(student.id).catch((err) => {
        if (err.code !== 'member_in_use') throw err
        if (!window.confirm(`${err.message}\n\n${t('school.students.detachKeeps')}`)) {
          return undefined
        }
        return detachMember(student.id, { force: true })
      }),
    )

  if (students === null) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  if (!students.length) {
    return (
      <EmptyState title={t('school.students.none')}>
        {t('school.students.noneHint')} <Link to="/school/courses">{t('school.tabs.courses')}</Link>
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
        <h3>{t('school.students.title')}</h3>
        <p className="hint">{t('school.students.hint')}</p>

        <ul className="people-list">
          {students.map((student) => (
            <li key={student.id}>
              <div className="row">
                <span className="name">{fullName(student)}</span>
                {/* адрес — подпись к имени: у человека без имени `fullName`
                    и есть его адрес, и второй раз печатать его незачем */}
                {fullName(student) === student.email ? null : (
                  <span className="hint">{student.email}</span>
                )}
                {/* та же пометка, что в списке учителей и в составе курса:
                    учётка заведена и ждёт первого входа через Google */}
                {student.arrived ? null : (
                  <span className="tag pending" title={t('school.people.waitingHint')}>
                    {t('school.people.waiting')}
                  </span>
                )}
                <button
                  type="button"
                  className="link detach"
                  disabled={busy}
                  onClick={() => detach(student)}
                >
                  {t('school.students.detach')}
                </button>
              </div>

              <div className="row courses">
                {student.courses.length === 0 ? (
                  <span className="hint">{t('school.students.noCourses')}</span>
                ) : (
                  student.courses.map((course) => (
                    <span
                      className={course.active ? 'tag' : 'tag past'}
                      key={course.row}
                      title={course.active ? undefined : t('school.students.removed')}
                    >
                      {course.name}
                    </span>
                  ))
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}
