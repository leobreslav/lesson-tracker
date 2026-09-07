import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import EmptyState from './EmptyState'
import {
  addHomegroupStudent,
  addParent,
  detachMember,
  fetchHomegroupStudents,
  fetchHomegroups,
  fetchMembers,
  removeHomegroupStudent,
  removeParent,
} from './api'
import { useSchoolSection } from './School'

const fullName = (person) =>
  [person.first_name, person.last_name].filter(Boolean).join(' ') || person.email

/**
 * Родители ученика — там же, где на него смотрят.
 *
 * Заводит их обычно импорт из ManageBac, но одного родителя надо уметь
 * добавить руками — того, кого в файле не было. Ввод — адрес: у
 * администратора список школы, а не наши номера; родителя, которого ещё
 * нет, сервер заведёт тем же движением. Снятие связи — крестик: «бывшее
 * родство» не состояние, о котором кто-то спросит.
 */
function Parents({ student, busy, run }) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const [email, setEmail] = useState('')

  const submit = (event) => {
    event.preventDefault()
    if (!email.trim()) return
    run(() =>
      addParent(student.id, email.trim()).then(() => {
        setEmail('')
        setAdding(false)
      }),
    )
  }

  return (
    <div className="row parents">
      <span className="hint">{t('school.students.parents')}</span>
      {student.parents.length === 0 && !adding && (
        <span className="hint">{t('school.students.noParents')}</span>
      )}
      {student.parents.map((parent) => (
        <span className="tag parent" key={parent.link} title={parent.email}>
          {parent.name}
          {parent.relation ? ` · ${parent.relation}` : ''}
          {parent.arrived ? null : (
            <span className="tag pending" title={t('school.people.waitingHint')}>
              {t('school.people.waiting')}
            </span>
          )}
          <button
            type="button"
            className="link"
            disabled={busy}
            aria-label={t('school.students.unlink', { name: parent.name })}
            onClick={() => run(() => removeParent(parent.link))}
          >
            ✕
          </button>
        </span>
      ))}
      {adding ? (
        <form className="row inline-form" onSubmit={submit}>
          <input
            type="email"
            value={email}
            required
            autoFocus
            disabled={busy}
            placeholder={t('school.students.parentEmail')}
            aria-label={t('school.students.parentEmail')}
            onChange={(event) => setEmail(event.target.value)}
          />
          <button type="submit" disabled={busy || !email.trim()}>
            {t('common.add')}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              setAdding(false)
              setEmail('')
            }}
          >
            {t('common.cancel')}
          </button>
        </form>
      ) : (
        <button
          type="button"
          className="link"
          disabled={busy}
          onClick={() => setAdding(true)}
        >
          {t('school.students.addParent')}
        </button>
      )}
    </div>
  )
}

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
 *
 * **Класс живёт здесь же, и это не соседство ради удобства.** Класс — это
 * свойство человека, а не список, который кто-то ведёт отдельно: из него
 * выводится, какие классы у курса, и на нём держится предупреждение «ученик
 * стоит в двух местах». Поэтому назначается он там, где на человека
 * смотрят, — и одним селектом, а не окном: у него ровно одно значение.
 *
 * Класс на год один, поэтому выбор класса из другого — это **перевод**:
 * прежняя строка закрывается, новая заводится, и то, что человек был в 6А,
 * остаётся правдой.
 */
export default function SchoolStudents() {
  const { t } = useTranslation()
  const { onLoggedOut } = useSchoolSection()
  const [students, setStudents] = useState(null)
  const [homegroups, setHomegroups] = useState([])
  // ученик → его действующая строка принадлежности классу
  const [membership, setMembership] = useState(new Map())
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
        fetchMembers({ kind: 'student' }),
        fetchHomegroups(),
        fetchHomegroupStudents(),
      ]).then(([people, groups, rows]) => {
        setStudents(people)
        setHomegroups(groups)
        setMembership(new Map(rows.map((row) => [row.student, row])))
      }),
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

  /**
   * Перевести ученика в другой класс — или вывести его из класса вовсе.
   *
   * Прежняя строка **закрывается**, а не удаляется: расписание сентября
   * собиралось по тому составу, и «его там не было» задним числом было бы
   * неправдой. Поэтому здесь два запроса подряд, а не один PATCH.
   */
  const moveTo = (student, groupId) =>
    run(async () => {
      const current = membership.get(student.id)
      if (current?.homegroup === groupId) return
      if (current) await removeHomegroupStudent(current.id)
      if (groupId) await addHomegroupStudent(groupId, student.id)
    })

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
                {/* класс — свойство человека, и правится там, где на
                    человека смотрят. Пусто значит «ни в одном»: бывает и
                    это, и молчать об этом нельзя */}
                {homegroups.length > 0 && (
                  <label className="checkbox">
                    {t('school.students.homegroup')}
                    <select
                      value={membership.get(student.id)?.homegroup ?? ''}
                      disabled={busy}
                      onChange={(event) =>
                        moveTo(
                          student,
                          event.target.value ? Number(event.target.value) : null,
                        )
                      }
                    >
                      <option value="">{t('school.students.noHomegroup')}</option>
                      {homegroups.map((group) => (
                        <option key={group.id} value={group.id}>
                          {group.name}
                        </option>
                      ))}
                    </select>
                  </label>
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

              <Parents student={student} busy={busy} run={run} />
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}
