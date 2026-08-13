import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  createGrade,
  createSubject,
  deleteGrade,
  deleteSubject,
  fetchGrades,
  fetchSubjects,
  renameSubject,
  updateGrade,
} from './api'
import { useSchoolSection } from './School'

const MAX_LEVEL = 11

/**
 * The two lists a course is built from: subjects and year groups.
 *
 * A year group has two fields and they are not the same thing. `level` is
 * the year of study counted from the first one — what sorting runs on;
 * `name` is what the school writes on the door. «MYP 4» is the ninth year of
 * study, so its level is 9, and a school that uses MYP labels next to plain
 * numbers still gets its courses in the right order.
 *
 * Both lists refuse to delete an entry a course still points at, and say how
 * many are in the way.
 */
export default function SchoolReference() {
  const { t } = useTranslation()
  const { onLoggedOut } = useSchoolSection()
  const [subjects, setSubjects] = useState(null)
  const [grades, setGrades] = useState([])
  const [subjectName, setSubjectName] = useState('')
  const [grade, setGrade] = useState({ level: '', name: '' })
  const [editing, setEditing] = useState(null) // {kind, id, value}
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
      Promise.all([fetchSubjects(), fetchGrades()])
        .then(([subjectList, gradeList]) => {
          setSubjects(subjectList)
          setGrades(gradeList)
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

  const addSubject = (event) => {
    event.preventDefault()
    const value = subjectName.trim()
    if (!value || busy) return
    run(() => createSubject(value).then(() => setSubjectName('')))
  }

  const addGrade = (event) => {
    event.preventDefault()
    const name = grade.name.trim()
    if (!name || !grade.level || busy) return
    run(() =>
      createGrade({ level: Number(grade.level), name }).then(() =>
        setGrade({ level: '', name: '' }),
      ),
    )
  }

  const commit = () => {
    if (!editing) return
    const { kind, id, value } = editing
    setEditing(null)

    const trimmed = value.trim()
    if (!trimmed) return
    run(() =>
      kind === 'subject' ? renameSubject(id, trimmed) : updateGrade(id, { name: trimmed }),
    )
  }

  const editable = (kind, item) =>
    editing?.kind === kind && editing.id === item.id ? (
      <input
        autoFocus
        value={editing.value}
        maxLength={kind === 'subject' ? 100 : 50}
        aria-label={t('school.reference.newName')}
        onChange={(event) => setEditing({ ...editing, value: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setEditing(null)
          if (event.key === 'Enter') commit()
        }}
        onBlur={commit}
      />
    ) : (
      <button
        type="button"
        className="link name"
        title={t('classes.rename')}
        disabled={busy}
        onClick={() => setEditing({ kind, id: item.id, value: item.name })}
      >
        {item.name}
      </button>
    )

  if (subjects === null) {
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
        <h3>{t('school.reference.subjects')}</h3>
        <p className="hint">{t('school.reference.subjectsHint')}</p>

        <form className="add-form" onSubmit={addSubject}>
          <input
            value={subjectName}
            maxLength={100}
            placeholder={t('school.courses.newSubject')}
            aria-label={t('school.courses.newSubject')}
            disabled={busy}
            onChange={(event) => setSubjectName(event.target.value)}
          />
          <button type="submit" disabled={busy || !subjectName.trim()}>
            {t('common.add')}
          </button>
        </form>

        <ul className="class-list">
          {subjects.map((subject) => (
            <li key={subject.id}>
              {editable('subject', subject)}
              <span className="hint">
                {t('school.reference.usedBy', { count: subject.courses })}
              </span>
              <button
                type="button"
                className="link"
                aria-label={t('school.reference.delete', { name: subject.name })}
                disabled={busy}
                onClick={() => run(() => deleteSubject(subject.id))}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h3>{t('school.reference.grades')}</h3>
        <p className="hint">{t('school.reference.gradesHint')}</p>

        <form className="add-form" onSubmit={addGrade}>
          <input
            type="number"
            min={1}
            max={MAX_LEVEL}
            value={grade.level}
            placeholder={t('school.reference.levelPlaceholder')}
            aria-label={t('school.reference.level')}
            disabled={busy}
            onChange={(event) =>
              setGrade((current) => ({ ...current, level: event.target.value }))
            }
          />
          <input
            value={grade.name}
            maxLength={50}
            placeholder={t('school.reference.namePlaceholder')}
            aria-label={t('school.reference.name')}
            disabled={busy}
            onChange={(event) =>
              setGrade((current) => ({ ...current, name: event.target.value }))
            }
          />
          <button type="submit" disabled={busy || !grade.name.trim() || !grade.level}>
            {t('common.add')}
          </button>
        </form>

        <ul className="class-list">
          {grades.map((item) => (
            <li key={item.id}>
              <span className="hint level">
                {t('school.reference.levelShort', { level: item.level })}
              </span>
              {editable('grade', item)}
              <span className="hint">
                {t('school.reference.usedBy', { count: item.courses })}
              </span>
              <button
                type="button"
                className="link"
                aria-label={t('school.reference.delete', { name: item.name })}
                disabled={busy}
                onClick={() => run(() => deleteGrade(item.id))}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}
