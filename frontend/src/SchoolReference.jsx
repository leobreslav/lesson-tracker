import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  addGradePreset,
  clearUnusedGrades,
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

// the two sets worth one button each: eleven years is the usual local
// system, thirteen the British and IB one
const PRESETS = [11, 13]

/**
 * The two lists a course is built from: subjects and year groups.
 *
 * A year group has two fields and they are not the same thing. `level` is
 * the year of study counted from the first one — what sorting runs on;
 * `name` is what the school writes on the door. «MYP 4» is the ninth year of
 * study, so its level is 9, and a school that uses MYP labels next to plain
 * numbers still gets its courses in the right order.
 *
 * That explanation used to sit above the form as three permanent lines,
 * where it was read once and then re-read forever. It now lives on the «?»
 * next to the field, and the list itself says nothing about years at all:
 * the number, greyed, in front of the name is the whole of it.
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
  // `named` — трогали ли поле названия: пока нет, оно следует за уровнем
  const [grade, setGrade] = useState({ level: '', name: '', named: false })
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
        setGrade({ level: '', name: '', named: false }),
      ),
    )
  }

  /**
   * Typing the year fills the name with «Grade N».
   *
   * Only until the name is touched: in the ordinary case the second field is
   * never typed in at all, and a school that writes «MYP 4» types it once
   * and keeps it.
   */
  const takeLevel = (value) =>
    setGrade((current) => ({
      ...current,
      level: value,
      name: current.named ? current.name : value ? `Grade ${value}` : '',
    }))

  const addPreset = (through) => addGradePreset(through)

  const clearUnused = () => clearUnusedGrades()

  const commit = () => {
    if (!editing) return
    const { kind, id, value } = editing
    setEditing(null)

    const trimmed = value.trim()
    if (!trimmed) return

    if (kind === 'subject') return run(() => renameSubject(id, trimmed))
    if (kind === 'level') return run(() => updateGrade(id, { level: Number(trimmed) }))
    return run(() => updateGrade(id, { name: trimmed }))
  }

  /**
   * The year of study, greyed, in front of the name.
   *
   * Editable only while nothing uses it: moving a year group that courses
   * sit on would reshuffle every sorted list without saying so, and the
   * server refuses it anyway. A typo in an empty one is just a typo.
   */
  const level = (item) => {
    if (editing?.kind === 'level' && editing.id === item.id) {
      return (
        <input
          autoFocus
          type="number"
          min={1}
          className="level-input"
          value={editing.value}
          aria-label={t('school.reference.level')}
          onChange={(event) => setEditing({ ...editing, value: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setEditing(null)
            if (event.key === 'Enter') commit()
          }}
          onBlur={commit}
        />
      )
    }

    if (item.courses) {
      return (
        <span className="hint level" title={t('school.reference.levelLocked')}>
          {item.level}
        </span>
      )
    }

    return (
      <button
        type="button"
        className="link hint level"
        title={t('school.reference.levelEdit')}
        disabled={busy}
        onClick={() =>
          setEditing({ kind: 'level', id: item.id, value: String(item.level) })
        }
      >
        {item.level}
      </button>
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

  const unused = grades.filter((item) => !item.courses).length

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

      <section className="panel" data-panel="subjects">
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

      <section className="panel" data-panel="grades">
        <h3>{t('school.reference.grades')}</h3>

        {grades.length === 0 ? (
          <div className="empty-inline">
            <p className="hint">{t('school.reference.gradesEmpty')}</p>
            <p className="hint">{t('school.reference.presetHint')}</p>
          </div>
        ) : (
          <ul className="class-list grade-list">
            {grades.map((item) => (
              // data-level: по тексту строку не поймать, пока её правят —
              // название на это время уезжает в поле ввода
              <li key={item.id} data-level={item.level}>
                {level(item)}
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
        )}

        <form className="add-form" onSubmit={addGrade}>
          <label className="field-with-hint">
            <span>
              {t('school.reference.level')}
              <abbr title={t('school.reference.levelExplain')}>?</abbr>
            </span>
            <input
              type="number"
              min={1}
              value={grade.level}
              placeholder={t('school.reference.levelPlaceholder')}
              aria-label={t('school.reference.level')}
              title={t('school.reference.levelExplain')}
              disabled={busy}
              onChange={(event) => takeLevel(event.target.value)}
            />
          </label>
          <label className="field-with-hint">
            <span>{t('school.reference.name')}</span>
            <input
              value={grade.name}
              maxLength={50}
              placeholder={t('school.reference.namePlaceholder')}
              aria-label={t('school.reference.name')}
              disabled={busy}
              onChange={(event) =>
                setGrade((current) => ({
                  ...current,
                  name: event.target.value,
                  named: true,
                }))
              }
            />
          </label>
          <button type="submit" disabled={busy || !grade.name.trim() || !grade.level}>
            {t('common.add')}
          </button>
        </form>

        {/* наборы доступны всегда, а не только в пустом состоянии: школа,
            заведшая четыре параллели, не должна вбивать девять руками.
            Кнопка добавляет недостающее, поэтому нажать её дважды не страшно */}
        <div className="row preset-row">
          {PRESETS.map((through) => (
            <button
              key={through}
              type="button"
              className={grades.length ? 'secondary' : ''}
              disabled={busy}
              onClick={() => run(() => addPreset(through))}
            >
              {t('school.reference.preset', { through })}
            </button>
          ))}

          {unused > 0 && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                if (
                  !window.confirm(t('school.reference.clearConfirm', { count: unused }))
                )
                  return
                run(clearUnused)
              }}
            >
              {t('school.reference.clearUnused', { count: unused })}
            </button>
          )}
        </div>
      </section>
    </>
  )
}
