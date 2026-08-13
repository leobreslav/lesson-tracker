import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import EmptyState from './EmptyState'
import Modal from './Modal'
import {
  deleteTemplate,
  fetchCourses,
  fetchSubjects,
  fetchTemplate,
  fetchTemplates,
  importTemplate,
  updateTemplate,
} from './api'

/**
 * The school's shelf of lesson plans.
 *
 * Everybody in the school reads it; what you see is every published plan
 * plus your own drafts. The server decides that — the list simply draws what
 * it is given, and the buttons follow the `can_edit` / `can_delete` flags
 * that come with each entry rather than second-guessing the rules here.
 */
export default function Library({ onLoggedOut }) {
  const { t } = useTranslation()
  const [templates, setTemplates] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [courses, setCourses] = useState([])
  const [filters, setFilters] = useState({ subject: '', grade: '', mine: false })
  const [opened, setOpened] = useState(null)
  const [importing, setImporting] = useState(null)
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

  const load = useCallback(() => {
    const params = {}
    if (filters.subject) params.subject = filters.subject
    if (filters.grade) params.grade = filters.grade
    if (filters.mine) params.mine = 'true'

    return fetchTemplates(params).then(setTemplates).catch(handleError)
  }, [filters, handleError])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    fetchSubjects().then(setSubjects).catch(handleError)
    fetchCourses().then(setCourses).catch(handleError)
  }, [handleError])

  const grades = useMemo(
    () => [...new Set((templates ?? []).map((item) => item.grade))].sort((a, b) => a - b),
    [templates],
  )

  const run = async (request, describe) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await request()
      await load()
      if (describe) setNotice(describe(result))
      return result
    } catch (err) {
      handleError(err)
      return null
    } finally {
      setBusy(false)
    }
  }

  const remove = (template) => {
    if (!window.confirm(t('library.deleteConfirm', { title: template.title }))) return
    run(() => deleteTemplate(template.id))
    setOpened(null)
  }

  const publish = (template, published) =>
    run(() => updateTemplate(template.id, { is_published: published })).then(() =>
      setOpened((current) =>
        current && current.id === template.id
          ? { ...current, is_published: published }
          : current,
      ),
    )

  if (templates === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('library.title')}</h1>
      </header>

      <p className="hint">{t('library.hint')}</p>

      <div className="class-filter">
        <label className="checkbox">
          {t('library.subject')}
          <select
            value={filters.subject}
            onChange={(event) =>
              setFilters({ ...filters, subject: event.target.value })
            }
          >
            <option value="">{t('library.anySubject')}</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </select>
        </label>

        <label className="checkbox">
          {t('library.grade')}
          <select
            value={filters.grade}
            onChange={(event) => setFilters({ ...filters, grade: event.target.value })}
          >
            <option value="">{t('library.anyGrade')}</option>
            {grades.map((grade) => (
              <option key={grade} value={grade}>
                {grade}
              </option>
            ))}
          </select>
        </label>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={filters.mine}
            onChange={(event) => setFilters({ ...filters, mine: event.target.checked })}
          />
          {t('library.onlyMine')}
        </label>
      </div>

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

      {!templates.length && (
        <EmptyState title={t('library.empty.title')}>{t('library.empty.hint')}</EmptyState>
      )}

      <ul className="class-list template-list">
        {templates.map((template) => (
          <li key={template.id}>
            <button
              type="button"
              className="link name"
              onClick={() =>
                fetchTemplate(template.id).then(setOpened).catch(handleError)
              }
            >
              {template.title}
            </button>
            <span className="hint">
              {t('library.line', {
                subject: template.subject_name,
                grade: template.grade,
                author: template.author_name || '—',
                lessons: t('common.lessonCount', { count: template.lessons }),
              })}
            </span>
            {!template.is_published && (
              <span className="badge">{t('library.draft')}</span>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => setImporting(template)}
            >
              {t('library.use')}
            </button>
          </li>
        ))}
      </ul>

      {opened && (
        <TemplateView
          template={opened}
          busy={busy}
          onPublish={publish}
          onDelete={remove}
          onUse={() => {
            setImporting(opened)
            setOpened(null)
          }}
          onClose={() => setOpened(null)}
        />
      )}

      {importing && (
        <UseTemplateDialog
          template={importing}
          courses={courses}
          busy={busy}
          onSubmit={(payload) =>
            run(
              () => importTemplate(payload),
              (result) =>
                t('library.imported', {
                  lessons: t('common.lessonCount', { count: result.created_lessons }),
                  blocks: result.created_headers,
                }),
            ).then(() => setImporting(null))
          }
          onClose={() => setImporting(null)}
        />
      )}
    </main>
  )
}

/**
 * The contents of a template, read-only.
 *
 * Editing the lines happens in a course plan and comes back through
 * «refresh from plan» — the template is a snapshot of a plan, so the plan
 * page is the one editor there needs to be.
 */
function TemplateView({ template, busy, onPublish, onDelete, onUse, onClose }) {
  const { t } = useTranslation()
  let number = 0

  return (
    <Modal onClose={onClose}>
      <h3>{template.title}</h3>
      <p className="hint">
        {t('library.line', {
          subject: template.subject_name,
          grade: template.grade,
          author: template.author_name || '—',
          lessons: t('common.lessonCount', { count: template.lessons }),
        })}
      </p>
      {template.description && <p>{template.description}</p>}

      <ul className="plan-preview">
        {template.rows.map((row) => {
          if (!row.is_header) number += 1
          return (
            <li key={row.id} className={row.is_header ? 'section' : 'lesson'}>
              {row.is_header ? (
                <strong>{row.title}</strong>
              ) : (
                <>
                  <span className="plan-number">{number}.</span> {row.title}
                </>
              )}
              {row.note && <span className="hint">{row.note}</span>}
            </li>
          )
        })}
      </ul>

      <div className="actions wrap">
        <button type="button" disabled={busy} onClick={onUse}>
          {t('library.use')}
        </button>

        {template.can_edit && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => onPublish(template, !template.is_published)}
          >
            {t(template.is_published ? 'library.unpublish' : 'library.publish')}
          </button>
        )}

        {template.can_delete && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => onDelete(template)}
          >
            {t('common.delete')}
          </button>
        )}

        <button type="button" className="secondary" onClick={onClose}>
          {t('agenda.menu.close')}
        </button>
      </div>
    </Modal>
  )
}

/** Choosing which course gets the copy, and what happens to what is there. */
function UseTemplateDialog({ template, courses, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [courseId, setCourseId] = useState(courses[0]?.id ?? null)
  const [mode, setMode] = useState('replace')

  const submit = (event) => {
    event.preventDefault()
    if (!courseId) return
    onSubmit({ course: courseId, template: template.id, mode })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h3>{t('library.useTitle', { title: template.title })}</h3>
        <p className="hint">{t('library.once')}</p>

        <label>
          {t('school.courses.title')}
          <select
            autoFocus
            value={courseId ?? ''}
            disabled={busy}
            onChange={(event) => setCourseId(Number(event.target.value))}
          >
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>

        <div className="row">
          <label className="checkbox">
            <input
              type="radio"
              name="use-mode"
              checked={mode === 'replace'}
              onChange={() => setMode('replace')}
            />
            {t('csv.modeReplace')}
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="use-mode"
              checked={mode === 'append'}
              onChange={() => setMode('append')}
            />
            {t('csv.modeAppend')}
          </label>
        </div>

        <p className="hint">
          {t('library.preview', {
            lessons: t('common.lessonCount', { count: template.lessons }),
            // the list carries no rows, only the detail view does
            blocks: (template.rows ?? []).filter((row) => row.is_header).length,
          })}
        </p>

        {mode === 'replace' && <p className="error">{t('csv.replaceWarning')}</p>}

        <div className="actions">
          <button type="submit" disabled={busy || !courseId}>
            {t('library.use')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
