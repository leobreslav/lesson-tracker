import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import EmptyState from './EmptyState'
import { formatSize, iconFor, looksLikeUrl } from './fileKind'
import { useKept } from './remember'
import {
  addBookmark,
  createBookmarkFolder,
  deleteAttachment,
  deleteBookmarkFolder,
  fetchBookmarkFolders,
  fetchBookmarks,
  openAttachment,
  renameBookmarkFolder,
  updateBookmark,
  uploadAttachment,
} from './api'

/* Два «места», которых нет в базе: весь стол и то, что лежит вне папок. */
const ALL = 'all'
const LOOSE = 'loose'

/**
 * Закладки: личный стол сотрудника.
 *
 * Файл, ссылка и записка — те же три вида материала, что у урока, и это не
 * совпадение: на сервере это одно и то же вложение, у которого владельцем
 * стал человек. Поэтому и заводятся они здесь тем же жестом, что в панели
 * урока — одно поле и зона перетаскивания, — а вид решает написанное:
 * целиком адрес значит ссылку, всё остальное записку.
 *
 * **Стол приезжает целиком, одним списком вещей и одним списком папок**, и
 * раскладывает их эта страница. Отсюда две вещи, которых иначе не было бы:
 * поиск идёт по всему столу сразу, не спрашивая сервер на каждую букву, а
 * лежащее вне папок — обычная строка того же списка, а не особый случай.
 *
 * Чужого здесь не бывает вовсе: ни у администратора школы, ни у методиста
 * доступа к чужому столу нет, и «показать коллеге» тут не действие, которое
 * забыли сделать, — это то, чего раздел не умеет намеренно.
 */
export default function Bookmarks({ user, onLoggedOut }) {
  const { t } = useTranslation()

  const [folders, setFolders] = useState(null)
  const [items, setItems] = useState([])
  // открытая папка — поза за работой, а не настройка: живёт во вкладке
  const [open, setOpen] = useKept('bookmarks.open', ALL)
  const [query, setQuery] = useKept('bookmarks.query', '')

  const [draft, setDraft] = useState({ what: '', title: '', note: '' })
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ title: '', note: '', folder: '' })
  const [folderDraft, setFolderDraft] = useState('')
  const [renaming, setRenaming] = useState(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [over, setOver] = useState(false)
  const fileInput = useRef(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () =>
      Promise.all([fetchBookmarkFolders(), fetchBookmarks(user.id)])
        .then(([shelves, things]) => {
          setFolders(shelves)
          setItems(things)
        })
        .catch(handleError),
    [handleError, user.id],
  )

  useEffect(() => {
    load()
  }, [load])

  /* Папку могли снести в другой вкладке — открытой останется её номер, и
     страница показывала бы пустоту вместо стола. */
  useEffect(() => {
    if (!folders || typeof open !== 'number') return
    if (!folders.some((folder) => folder.id === open)) setOpen(ALL)
  }, [folders, open, setOpen])

  const searching = query.trim().length > 0
  const folderId = typeof open === 'number' ? open : null

  const shown = useMemo(() => {
    if (searching) {
      const needle = query.trim().toLowerCase()
      return items.filter((item) =>
        [item.title, item.note, item.url]
          .filter(Boolean)
          .some((text) => text.toLowerCase().includes(needle)),
      )
    }
    if (open === ALL) return items
    if (open === LOOSE) return items.filter((item) => !item.bookmark_folder)
    return items.filter((item) => item.bookmark_folder === open)
  }, [items, open, query, searching])

  const countIn = (folder) =>
    items.filter((item) => item.bookmark_folder === folder).length

  // --- заведение ---

  const attach = async (files) => {
    if (!files.length) return
    setBusy(true)
    setError(null)
    try {
      for (const file of files) {
        await uploadAttachment({
          bookmarkOwner: user.id,
          bookmarkFolder: folderId ?? undefined,
          file,
          // приписка, набранная до выбора файла, относится к нему: человек
          // объясняет, зачем несёт файл, а не пишет отдельную записку.
          // Название не шлём вовсе — им станет имя файла
          note: draft.note.trim(),
        })
      }
      setDraft({ what: '', title: '', note: '' })
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /**
   * Одна вещь из одного поля.
   *
   * Что это — решает написанное, а не заданный заранее вопрос: целиком
   * адрес значит ссылку, всё остальное — записку. То же правило, что в
   * панели урока, и живёт оно там же (`fileKind.looksLikeUrl`).
   */
  const submit = async (event) => {
    event.preventDefault()
    const what = draft.what.trim()
    if (!what) return

    setBusy(true)
    setError(null)
    try {
      await addBookmark({
        owner: user.id,
        folder: folderId,
        url: looksLikeUrl(what) ? what : '',
        title: looksLikeUrl(what) ? draft.title.trim() || what : what,
        note: draft.note.trim(),
      })
      setDraft({ what: '', title: '', note: '' })
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const addFolder = async (event) => {
    event.preventDefault()
    const title = folderDraft.trim()
    if (!title) return

    setBusy(true)
    setError(null)
    try {
      const folder = await createBookmarkFolder(title)
      setFolderDraft('')
      await load()
      // заводят папку тогда, когда есть что в неё положить, — поэтому она
      // сразу и открывается
      setOpen(folder.id)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  // --- правка ---

  const startEdit = (item) => {
    setEditing(item.id)
    setForm({
      title: item.title,
      note: item.note ?? '',
      folder: item.bookmark_folder ?? '',
    })
  }

  const saveEdit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await updateBookmark(editing, {
        title: form.title.trim(),
        note: form.note,
        // пустая строка селекта — это «на виду», то есть `null`, а не
        // «поле не трогали»
        folder: form.folder === '' ? null : Number(form.folder),
      })
      setEditing(null)
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (item) => {
    if (!window.confirm(t('bookmarks.removeItem', { title: item.title }))) return

    setBusy(true)
    setError(null)
    try {
      await deleteAttachment(item.id)
      setItems((current) => current.filter((row) => row.id !== item.id))
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const saveFolderName = async (event) => {
    event.preventDefault()
    const title = renaming.trim()
    if (!title) return

    setBusy(true)
    setError(null)
    try {
      await renameBookmarkFolder(folderId, title)
      setRenaming(null)
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const removeFolder = async () => {
    const folder = folders.find((one) => one.id === folderId)
    if (!window.confirm(t('bookmarks.removeFolder', { title: folder.title }))) return

    setBusy(true)
    setError(null)
    try {
      await deleteBookmarkFolder(folderId)
      setOpen(ALL)
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const download = async (item) => {
    setError(null)
    try {
      await openAttachment(item.id)
    } catch (err) {
      handleError(err)
    }
  }

  // --- отрисовка ---

  const folderName = (id) => folders?.find((one) => one.id === id)?.title

  const pick = (value, label, count) => (
    <li key={String(value)}>
      <button
        type="button"
        className={open === value && !searching ? 'shelf-pick active' : 'shelf-pick'}
        onClick={() => {
          setOpen(value)
          setQuery('')
        }}
      >
        <span className="title">{label}</span>
        <span className="hint">{count}</span>
      </button>
    </li>
  )

  const itemRow = (item) => {
    const size = formatSize(item.size)

    if (editing === item.id) {
      return (
        <li key={item.id} className="attachment shelf-item editing">
          <form className="shelf-edit" onSubmit={saveEdit}>
            <div className="row">
              <input
                value={form.title}
                maxLength={200}
                aria-label={t('bookmarks.itemTitle')}
                placeholder={t('bookmarks.itemTitle')}
                onChange={(event) =>
                  setForm({ ...form, title: event.target.value })
                }
              />
              <select
                value={form.folder}
                aria-label={t('bookmarks.folder')}
                onChange={(event) =>
                  setForm({ ...form, folder: event.target.value })
                }
              >
                <option value="">{t('bookmarks.loose')}</option>
                {folders.map((folder) => (
                  <option key={folder.id} value={folder.id}>
                    {folder.title}
                  </option>
                ))}
              </select>
            </div>

            <textarea
              className="shelf-note"
              rows={2}
              value={form.note}
              maxLength={2000}
              aria-label={t('bookmarks.note')}
              placeholder={t('bookmarks.notePlaceholder')}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
            />

            <div className="row">
              <button type="submit" disabled={busy || !form.title.trim()}>
                {t('common.save')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setEditing(null)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </form>
        </li>
      )
    }

    return (
      <li key={item.id} className="attachment shelf-item">
        <span className="attachment-icon" aria-hidden="true">
          {iconFor(item)}
        </span>

        {/* у записки нет цели: она сама и есть весь материал, нажимать
            на неё некуда */}
        {item.kind === 'text' ? (
          <span className="title">{item.title}</span>
        ) : item.kind === 'link' ? (
          <a href={item.url} target="_blank" rel="noreferrer" className="title">
            {item.title}
          </a>
        ) : (
          <button
            type="button"
            className="link title"
            title={t('bookmarks.download')}
            onClick={() => download(item)}
          >
            {item.title}
          </button>
        )}

        {size && (
          <span className="hint">
            {t(`lesson.size.${size.unit}`, { value: size.value })}
          </span>
        )}

        {/* какая это папка — видно только там, где список смешанный: внутри
            открытой папки подпись повторяла бы её заголовок в каждой строке */}
        {(searching || open === ALL) && item.bookmark_folder && (
          <span className="badge">{folderName(item.bookmark_folder)}</span>
        )}

        <button
          type="button"
          className="link"
          title={t('common.edit')}
          disabled={busy}
          onClick={() => startEdit(item)}
        >
          ✎
        </button>
        <button
          type="button"
          className="link remove"
          title={t('common.delete')}
          disabled={busy}
          onClick={() => remove(item)}
        >
          ✕
        </button>

        {item.note && <p className="note">{item.note}</p>}
      </li>
    )
  }

  if (!folders) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('bookmarks.title')}</h1>
        <p className="hint">{t('bookmarks.lead')}</p>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="shelf">
        <aside className="panel">
          <ul className="shelf-folders">
            {pick(ALL, t('bookmarks.all'), items.length)}
            {folders.map((folder) =>
              pick(folder.id, folder.title, countIn(folder.id)),
            )}
            {pick(LOOSE, t('bookmarks.loose'), countIn(null))}
          </ul>

          <form className="inline-form bare" onSubmit={addFolder}>
            <input
              value={folderDraft}
              maxLength={120}
              placeholder={t('bookmarks.folderPlaceholder')}
              aria-label={t('bookmarks.folderPlaceholder')}
              onChange={(event) => setFolderDraft(event.target.value)}
            />
            <button type="submit" disabled={busy || !folderDraft.trim()}>
              {t('common.add')}
            </button>
          </form>
        </aside>

        <section className="panel shelf-body">
          {renaming === null ? (
            <div className="row">
              <input
                className="search"
                value={query}
                maxLength={200}
                placeholder={t('bookmarks.search')}
                aria-label={t('bookmarks.search')}
                onChange={(event) => setQuery(event.target.value)}
              />
              {folderId !== null && !searching && (
                <>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => setRenaming(folderName(folderId))}
                  >
                    {t('bookmarks.rename')}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={removeFolder}
                  >
                    {t('common.delete')}
                  </button>
                </>
              )}
            </div>
          ) : (
            <form className="inline-form bare" onSubmit={saveFolderName}>
              <input
                value={renaming}
                maxLength={120}
                autoFocus
                aria-label={t('bookmarks.folderPlaceholder')}
                onChange={(event) => setRenaming(event.target.value)}
              />
              <button type="submit" disabled={busy || !renaming.trim()}>
                {t('common.save')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setRenaming(null)}
              >
                {t('common.cancel')}
              </button>
            </form>
          )}

          {shown.length > 0 && <ul className="attachments">{shown.map(itemRow)}</ul>}

          {shown.length === 0 && (
            <EmptyState title={t('bookmarks.empty.title')}>
              {searching ? t('bookmarks.empty.found') : t('bookmarks.empty.shelf')}
            </EmptyState>
          )}

          {/* Заводить можно и во время поиска, но кладётся оно **не туда,
              что нашлось**: поиск — это способ дойти до вещи, а не место.
              Поэтому форма показывает, куда именно ляжет новое. */}
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            aria-label={t('bookmarks.addFile')}
            onChange={(event) => {
              attach([...event.target.files])
              event.target.value = ''
            }}
          />

          <button
            type="button"
            className={over ? 'dropzone over' : 'dropzone'}
            disabled={busy}
            onClick={() => fileInput.current.click()}
            onDragOver={(event) => {
              event.preventDefault()
              setOver(true)
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(event) => {
              event.preventDefault()
              setOver(false)
              attach([...(event.dataTransfer?.files ?? [])])
            }}
          >
            {t('bookmarks.dropHere')}
          </button>

          <form className="shelf-add" onSubmit={submit}>
            <div className="row">
              <input
                value={draft.what}
                maxLength={200}
                placeholder={t('bookmarks.whatPlaceholder')}
                aria-label={t('bookmarks.what')}
                onChange={(event) => setDraft({ ...draft, what: event.target.value })}
              />
              {looksLikeUrl(draft.what) && (
                <input
                  value={draft.title}
                  maxLength={200}
                  placeholder={t('bookmarks.linkTitle')}
                  aria-label={t('bookmarks.linkTitle')}
                  onChange={(event) =>
                    setDraft({ ...draft, title: event.target.value })
                  }
                />
              )}
              <button type="submit" disabled={busy || !draft.what.trim()}>
                {t('common.add')}
              </button>
            </div>

            {/*
              Приписка стоит здесь, а не открывается правкой уже заведённого.

              Пишут её тогда же, когда кладут вещь: «зачем это мне» помнится
              ровно в этот момент и не помнится через неделю. Она же — способ
              записать длинное: название держит двести знаков и обрезается,
              а записка на три строки в него не помещается вовсе.

              И она относится к тому, что заводят **следующим**, включая
              файл: набрал, зачем несёшь, перетащил файл — приписка уехала
              вместе с ним.
            */}
            <textarea
              className="shelf-note"
              rows={2}
              value={draft.note}
              maxLength={2000}
              placeholder={t('bookmarks.notePlaceholder')}
              aria-label={t('bookmarks.note')}
              onChange={(event) => setDraft({ ...draft, note: event.target.value })}
            />
          </form>

          <p className="hint">
            {folderId === null
              ? t('bookmarks.willLieLoose')
              : t('bookmarks.willLieIn', { folder: folderName(folderId) })}
          </p>
        </section>
      </div>
    </main>
  )
}
