import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { longDate } from './dates'
import Modal from './Modal'
import Rendered from './Markdown'
import { formatSize, iconFor } from './fileKind'
import {
  addLinkAttachment,
  deleteAttachment,
  fetchPlanNode,
  openAttachment,
  updatePlanNode,
  uploadAttachment,
} from './api'

/**
 * One lesson, opened up: what it says and what comes with it.
 *
 * The plan table stays a table — a lesson body is a page of text and would
 * bury it. So the content lives here, in a sheet the full height of the
 * window, and the table only shows a mark that there is something to open.
 *
 * Two things are edited on different clocks, deliberately:
 *
 * * the **text** is a draft until «Save» — that is what the unsaved-changes
 *   mark is about, and why closing while dirty asks first;
 * * an **attachment** is a row of its own on the server, so adding or
 *   removing one takes effect at once. Holding a file hostage to a Save
 *   button would mean an upload that quietly never happened.
 */

const FIELDS = ['objectives', 'body', 'formative', 'homework']

const empty = { title: '', note: '', objectives: '', body: '', formative: '', homework: '' }

const pick = (node) =>
  Object.fromEntries(Object.keys(empty).map((field) => [field, node[field] ?? '']))

/**
 * `where` — где эта строка стоит: номер урока, дата по раскладке, проведено
 * ли занятие. Считает это страница плана: у неё есть и дерево с номерами, и
 * лента слотов, а панель знает только id и своё содержание.
 */
export default function LessonPanel({ nodeId, where = null, onClose, onSaved }) {
  const { t } = useTranslation()

  const [saved, setSaved] = useState(null)
  const [draft, setDraft] = useState(null)
  const [attachments, setAttachments] = useState([])
  const [expanded, setExpanded] = useState(() => new Set())
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [overDropZone, setOverDropZone] = useState(false)
  const [link, setLink] = useState(null) // {url, title} while the form is open

  const fileInput = useRef(null)

  useEffect(() => {
    let cancelled = false

    fetchPlanNode(nodeId)
      .then((node) => {
        if (cancelled) return
        setSaved(pick(node))
        setDraft(pick(node))
        setAttachments(node.attachments ?? [])
        // a field with something in it opens itself; an empty lesson opens
        // the body, so there is somewhere to start typing
        const filled = FIELDS.filter((field) => node[field]?.trim())
        setExpanded(new Set(filled.length ? filled : ['body']))
      })
      .catch((err) => !cancelled && setError(err.message))

    return () => {
      cancelled = true
    }
  }, [nodeId])

  const dirty = useMemo(
    () => Boolean(saved && draft) && FIELDS.concat('title', 'note').some(
      (field) => saved[field] !== draft[field],
    ),
    [saved, draft],
  )

  const set = (field, value) => setDraft((current) => ({ ...current, [field]: value }))

  const toggle = (field) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(field)) next.delete(field)
      else next.add(field)
      return next
    })

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const node = await updatePlanNode(nodeId, draft)
      setSaved(pick(node))
      onSaved?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** Closing with unsaved text asks; closing with everything saved does not. */
  const mayClose = () => !dirty || window.confirm(t('lesson.discard'))

  const close = () => {
    if (mayClose()) onClose()
  }

  // --- attachments ---

  const attach = async (files) => {
    setBusy(true)
    setError(null)

    try {
      for (const file of files) {
        const added = await uploadAttachment({ planRow: nodeId, file })
        setAttachments((current) => [...current, added])
      }
      onSaved?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const submitLink = async (event) => {
    event.preventDefault()
    if (!link.url.trim()) return

    setBusy(true)
    setError(null)
    try {
      const added = await addLinkAttachment({
        planRow: nodeId,
        url: link.url.trim(),
        title: link.title.trim() || link.url.trim(),
      })
      setAttachments((current) => [...current, added])
      setLink(null)
      onSaved?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (attachment) => {
    if (!window.confirm(t('lesson.removeAttachment', { title: attachment.title }))) {
      return
    }

    setBusy(true)
    setError(null)
    try {
      await deleteAttachment(attachment.id)
      setAttachments((current) => current.filter((item) => item.id !== attachment.id))
      onSaved?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const download = async (attachment) => {
    setError(null)
    try {
      await openAttachment(attachment.id)
    } catch (err) {
      setError(err.message)
    }
  }

  const onDrop = (event) => {
    event.preventDefault()
    setOverDropZone(false)
    const files = [...(event.dataTransfer?.files ?? [])]
    if (files.length) attach(files)
  }

  // --- rendering ---

  const field = (name) => {
    const value = draft[name]
    const isOpen = expanded.has(name)

    return (
      <section className="lesson-field" key={name} data-field={name}>
        <button
          type="button"
          className="lesson-field-head"
          aria-expanded={isOpen}
          onClick={() => toggle(name)}
        >
          <span className="caret">{isOpen ? '▾' : '▸'}</span>
          <span className="lesson-field-name">{t(`lesson.fields.${name}`)}</span>
          {value.trim() ? (
            <span className="dot" title={t('lesson.filled')} />
          ) : (
            <span className="hint">{t('lesson.blank')}</span>
          )}
        </button>

        {isOpen &&
          (preview ? (
            <Rendered text={value} />
          ) : (
            <textarea
              value={value}
              rows={name === 'body' ? 12 : 4}
              spellCheck
              aria-label={t(`lesson.fields.${name}`)}
              placeholder={t(`lesson.placeholders.${name}`)}
              onChange={(event) => set(name, event.target.value)}
            />
          ))}
      </section>
    )
  }

  const attachmentRow = (attachment) => {
    const size = formatSize(attachment.size)

    return (
      <li key={attachment.id} className="attachment">
        <span className="attachment-icon" aria-hidden="true">
          {iconFor(attachment)}
        </span>

        {attachment.kind === 'link' ? (
          <a href={attachment.url} target="_blank" rel="noreferrer" className="title">
            {attachment.title}
          </a>
        ) : (
          <button
            type="button"
            className="link title"
            title={t('lesson.download')}
            onClick={() => download(attachment)}
          >
            {attachment.title}
          </button>
        )}

        {size && (
          <span className="hint">{t(`lesson.size.${size.unit}`, { value: size.value })}</span>
        )}
        {attachment.is_shared && (
          <span className="badge" title={t('lesson.sharedHint')}>
            {t('lesson.shared')}
          </span>
        )}

        <button
          type="button"
          className="link remove"
          title={t('common.delete')}
          disabled={busy}
          onClick={() => remove(attachment)}
        >
          ✕
        </button>
      </li>
    )
  }

  return (
    <Modal className="sheet" onClose={onClose} onBeforeClose={mayClose}>
      {!draft ? (
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      ) : (
        <>
          <header className="lesson-head">
            {/*
              Чем эта запись является и куда ложится.

              Окно открывается из двух мест — из таблицы плана и со страницы
              занятия, — и во втором человек приходит сюда за правкой урока,
              а правит **строку программы**. Без этой шапки он не отличал бы
              одно от другого: заголовок, поле, кнопка — и ни слова о том,
              что перед ним.

              Дата названа «по раскладке» ровно потому, что она догадка:
              строка не привязана к дню, и её сдвинет любая правка плана
              выше. У проведённого занятия дата уже записана, и слово другое.
            */}
            {where && (
              <p className="hint lesson-where">
                {[
                  where.number
                    ? t('lesson.where.row', { number: where.number })
                    : t('lesson.where.plan'),
                  where.date
                    ? t(where.taught ? 'lesson.where.taughtOn' : 'lesson.where.planned', {
                        date: longDate(where.date),
                      })
                    : t('lesson.where.noSlot'),
                ].join(' · ')}
                {!where.taught && ` — ${t('lesson.where.notTaught')}`}
              </p>
            )}

            <div className="lesson-head-row">
            <input
              className="lesson-title"
              value={draft.title}
              maxLength={200}
              aria-label={t('plan.titleLabel')}
              onChange={(event) => set('title', event.target.value)}
            />
            <div className="actions">
              <button
                type="button"
                className={preview ? 'chip active' : 'chip'}
                aria-pressed={preview}
                onClick={() => setPreview(!preview)}
              >
                {t(preview ? 'lesson.edit' : 'lesson.preview')}
              </button>
            </div>
            </div>
          </header>

          <p className="lesson-status">
            {dirty ? (
              <span className="unsaved" role="status">
                ● {t('lesson.unsaved')}
              </span>
            ) : (
              <span className="hint" role="status">
                {t('lesson.allSaved')}
              </span>
            )}
          </p>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <input
            className="lesson-note"
            value={draft.note}
            maxLength={500}
            placeholder={t('plan.notePlaceholder')}
            aria-label={t('plan.noteLabel')}
            onChange={(event) => set('note', event.target.value)}
          />

          {FIELDS.map(field)}

          <section className="lesson-files">
            <h3>{t('lesson.attachments')}</h3>

            {attachments.length > 0 && (
              <ul className="attachments">{attachments.map(attachmentRow)}</ul>
            )}

            <div
              className={overDropZone ? 'dropzone over' : 'dropzone'}
              onDragOver={(event) => {
                event.preventDefault()
                setOverDropZone(true)
              }}
              onDragLeave={() => setOverDropZone(false)}
              onDrop={onDrop}
            >
              {t('lesson.dropHere')}
            </div>

            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              aria-label={t('lesson.addFile')}
              onChange={(event) => {
                attach([...event.target.files])
                event.target.value = ''
              }}
            />

            <div className="actions wrap">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => fileInput.current.click()}
              >
                {t('lesson.addFile')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setLink({ url: '', title: '' })}
              >
                {t('lesson.addLink')}
              </button>
            </div>

            {link && (
              <form className="inline-form" onSubmit={submitLink}>
                <input
                  autoFocus
                  value={link.url}
                  placeholder="https://…"
                  aria-label={t('lesson.linkUrl')}
                  onChange={(event) => setLink({ ...link, url: event.target.value })}
                />
                <input
                  value={link.title}
                  maxLength={200}
                  placeholder={t('lesson.linkTitle')}
                  aria-label={t('lesson.linkTitle')}
                  onChange={(event) => setLink({ ...link, title: event.target.value })}
                />
                <button type="submit" disabled={busy || !link.url.trim()}>
                  {t('common.add')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setLink(null)}
                >
                  {t('common.cancel')}
                </button>
              </form>
            )}
          </section>

          <footer className="actions lesson-foot">
            <button type="button" disabled={busy || !dirty} onClick={save}>
              {t('common.save')}
            </button>
          </footer>
        </>
      )}
    </Modal>
  )
}
