import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { longDate } from './dates'
import Modal from './Modal'
import Rendered from './Markdown'
import { formatSize, iconFor } from './fileKind'
import {
  addLinkAttachment,
  addTextAttachment,
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

/** Целиком адрес — и ничего кроме: пробел внутри уже делает это записью. */
const looksLikeUrl = (value) => /^https?:\/\/\S+$/i.test(value.trim())

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
  // одно поле на ссылку и запись: что именно набрали, видно из набранного
  const [draftResource, setDraftResource] = useState('')
  const [link, setLink] = useState({ url: '', title: '' })

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
        if (node.attachments?.length) filled.push('materials')
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

  /**
   * Один материал из одного поля.
   *
   * Что это — решает написанное: целиком адрес значит ссылку, всё остальное
   * запись. Правило сходится или не сходится, серединки нет, поэтому и
   * угадыванием это не является: «см. http://…» не адрес, значит запись.
   */
  const submitResource = async (event) => {
    event.preventDefault()
    const value = draftResource.trim()
    if (!value) return

    setBusy(true)
    setError(null)
    try {
      const added = looksLikeUrl(value)
        ? await addLinkAttachment({
            planRow: nodeId,
            url: value,
            title: link.title.trim() || value,
          })
        : await addTextAttachment({ planRow: nodeId, title: value })

      setAttachments((current) => [...current, added])
      setDraftResource('')
      setLink({ url: '', title: '' })
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

  /**
   * Шапка раздела: каретка, название и что внутри.
   *
   * В просмотре у пустого раздела разворачивать нечего, и он перестаёт быть
   * кнопкой вовсе: каретка, которая раскрывает пустоту, — обещание
   * содержимого, которого нет. В правке кнопка остаётся: там пустое поле
   * как раз и открывают, чтобы написать.
   */
  const head = (name, label, mark, frozen) =>
    frozen ? (
      <span className="lesson-field-head static">
        <span className="lesson-field-name">{label}</span>
        {mark}
      </span>
    ) : (
      <button
        type="button"
        className="lesson-field-head"
        aria-expanded={expanded.has(name)}
        onClick={() => toggle(name)}
      >
        <span className="caret">{expanded.has(name) ? '▾' : '▸'}</span>
        <span className="lesson-field-name">{label}</span>
        {mark}
      </button>
    )

  const field = (name) => {
    const value = draft[name]
    const frozen = preview && !value.trim()
    const isOpen = !frozen && expanded.has(name)

    return (
      <section
        className={frozen ? 'lesson-field frozen' : 'lesson-field'}
        key={name}
        data-field={name}
      >
        {head(
          name,
          t(`lesson.fields.${name}`),
          value.trim() ? (
            <span className="dot" title={t('lesson.filled')} />
          ) : (
            <span className="hint">{t('lesson.blank')}</span>
          ),
          frozen,
        )}

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

        {/* у записи нет цели: её название и есть весь материал, и нажимать
            на него некуда */}
        {attachment.kind === 'text' ? (
          <span className="title">{attachment.title}</span>
        ) : attachment.kind === 'link' ? (
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

        {!preview && (
          <button
            type="button"
            className="link remove"
            title={t('common.delete')}
            disabled={busy}
            onClick={() => remove(attachment)}
          >
            ✕
          </button>
        )}
      </li>
    )
  }

  return (
    <Modal
      className="sheet"
      onClose={onClose}
      onBeforeClose={mayClose}
      // заголовок окна: что именно правится. «Урок», а не «тема» — в этом
      // интерфейсе тема это папка, и рядом стоит кнопка «+ тема»
      title={t(where?.number ? 'lesson.where.row' : 'lesson.where.plan', {
        number: where?.number,
        course: where?.course ?? '',
      })}
      actions={
        <>
          {/* обе кнопки одной формы: круглая «таблетка» рядом с
              прямоугольной читалась как два разных сорта органов
              управления, хотя это просто переключатель и подтверждение */}
          <button
            type="button"
            className={preview ? 'secondary compact pressed' : 'secondary compact'}
            aria-pressed={preview}
            onClick={() => setPreview(!preview)}
          >
            {t(preview ? 'lesson.edit' : 'lesson.preview')}
          </button>
          <button
            type="button"
            className="compact"
            disabled={busy || !dirty}
            onClick={save}
          >
            {t('common.save')}
          </button>
        </>
      }
    >
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
                {where.date
                  ? t(where.taught ? 'lesson.where.taughtOn' : 'lesson.where.planned', {
                      date: longDate(where.date),
                    })
                  : t('lesson.where.noSlot')}
                {!where.taught && ` — ${t('lesson.where.notTaught')}`}
              </p>
            )}

            {/* В просмотре название и заметка — текст, а не поля: режим
                называется «просмотр», и поле ввода в нём обещает правку,
                которой не будет. Правится всё одной кнопкой, а не по
                частям */}
            {preview ? (
              <p className="lesson-title static">{draft.title}</p>
            ) : (
              <input
                className="lesson-title"
                value={draft.title}
                maxLength={200}
                aria-label={t('plan.titleLabel')}
                onChange={(event) => set('title', event.target.value)}
              />
            )}
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

          {preview
            ? draft.note.trim() && <p className="lesson-note static">{draft.note}</p>
            : (
                <input
                  className="lesson-note"
                  value={draft.note}
                  maxLength={500}
                  placeholder={t('plan.notePlaceholder')}
                  aria-label={t('plan.noteLabel')}
                  onChange={(event) => set('note', event.target.value)}
                />
              )}

          {FIELDS.map(field)}

          {/*
            Материалы — такой же раздел, как цели и ход урока, а не приписка
            снизу. Это список того, чем на уроке пользуются: файл, ссылка, а
            со временем и просто строка текста; разворачивается он и
            подписывается тем же способом, что остальные.
          */}
          <section
            className={
              preview && !attachments.length
                ? 'lesson-field lesson-files frozen'
                : 'lesson-field lesson-files'
            }
            data-field="materials"
          >
            {head(
              'materials',
              t('lesson.attachments'),
              attachments.length ? (
                <span className="hint">{attachments.length}</span>
              ) : (
                <span className="hint">{t('lesson.blank')}</span>
              ),
              preview && !attachments.length,
            )}

            {expanded.has('materials') && !(preview && !attachments.length) && (
            <>
            {attachments.length > 0 && (
              <ul className="attachments">{attachments.map(attachmentRow)}</ul>
            )}

            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              aria-label={t('lesson.add.file')}
              onChange={(event) => {
                attach([...event.target.files])
                event.target.value = ''
              }}
            />

            {/*
              Один ряд на два вида материала и зона на третий.

              Рядов было три — по одному на файл, ссылку и запись, — и это
              три белые карточки с тенью внутри серого блока: `.inline-form`
              задумана как отдельная карточка, и внутри раздела читалась как
              вложенное окно. Плюс две одинаковые синие «Добавить» друг под
              другом.

              А спрашивать вид отдельной строкой и не нужно: он **виден из
              написанного**. Целиком адрес — ссылка, всё остальное — запись.
              Правило сходится или не сходится, серединки у него нет: «см.
              http://…» это запись, потому что это не адрес. Тот же довод, по
              которому отсюда ушли кнопки «сейчас я буду добавлять ссылку»:
              решает набранное, а не объявленное заранее.

              Название спрашивается только у адреса и только потому, что
              голый URL в списке нечитаем; у записи название и есть она сама.
            */}
            {!preview && (
              <>
                {/* зона перетаскивания — она же кнопка выбора: тащить умеют
                    не все и не везде, а нажать везде */}
                <button
                  type="button"
                  className={overDropZone ? 'dropzone over' : 'dropzone'}
                  disabled={busy}
                  onClick={() => fileInput.current.click()}
                  onDragOver={(event) => {
                    event.preventDefault()
                    setOverDropZone(true)
                  }}
                  onDragLeave={() => setOverDropZone(false)}
                  onDrop={onDrop}
                >
                  {t('lesson.dropHere')}
                </button>

                <form className="inline-form bare" onSubmit={submitResource}>
                  <input
                    value={draftResource}
                    maxLength={500}
                    placeholder={t('lesson.resourcePlaceholder')}
                    aria-label={t('lesson.resourceLabel')}
                    onChange={(event) => setDraftResource(event.target.value)}
                  />
                  {looksLikeUrl(draftResource) && (
                    <input
                      value={link.title}
                      maxLength={200}
                      placeholder={t('lesson.linkTitle')}
                      aria-label={t('lesson.linkTitle')}
                      onChange={(event) =>
                        setLink({ ...link, title: event.target.value })
                      }
                    />
                  )}
                  <button type="submit" disabled={busy || !draftResource.trim()}>
                    {t('common.add')}
                  </button>
                </form>
              </>
            )}

            </>
            )}
          </section>

        </>
      )}
    </Modal>
  )
}
