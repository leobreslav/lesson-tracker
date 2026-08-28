import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import EmptyState from './EmptyState'
import { formatSize, iconFor, looksLikeUrl } from './fileKind'
import { useKept } from './remember'
import {
  addBookmark,
  addSchoolShelfItem,
  createBookmarkFolder,
  deleteAttachment,
  deleteBookmarkFolder,
  fetchBookmarkFolders,
  fetchBookmarks,
  fetchSchoolShelf,
  openAttachment,
  renameBookmarkFolder,
  updateBookmark,
  uploadAttachment,
} from './api'

/* Два «места», которых нет в базе: весь стол и то, что лежит вне папок. */
const ALL = 'all'
const LOOSE = 'loose'

const EMPTY_DRAFT = { what: '', title: '', note: '' }

/**
 * Закладки: полка школы сверху, личный стол под ней.
 *
 * Файл, ссылка и записка — те же три вида материала, что у урока, и это не
 * совпадение: на сервере это одно и то же вложение, у которого владельцем
 * стал человек или школа. Поэтому и заводятся они здесь тем же жестом, что в
 * панели урока — одно поле и зона перетаскивания, — а вид решает написанное:
 * целиком адрес значит ссылку, всё остальное записку.
 *
 * **Полок две, и они не равны.** Общая принадлежит школе: её наполняет
 * администратор, а сотрудники видят её над своим и не правят. Личная
 * принадлежит человеку, и чужой не бывает вовсе — ни у администратора, ни у
 * методиста. Строка при этом рисуется одна и та же: если бы они разошлись
 * видом, каждая следующая правка чинила бы одну из двух.
 *
 * **Стол приезжает целиком**, тремя списками, и раскладывает их эта
 * страница. Отсюда две вещи, которых иначе не было бы: поиск идёт по обеим
 * полкам сразу, не спрашивая сервер на каждую букву, а лежащее вне папок —
 * обычная строка того же списка, а не особый случай.
 */
export default function Bookmarks({ user, onLoggedOut }) {
  const { t } = useTranslation()

  // Школа у вошедшего может и отсутствовать — так живёт суперпользователь,
  // которого никто не приглашал. Общей полки у него нет вовсе, и спрашивать
  // её значило бы слать запрос с `undefined` в адресе.
  const schoolId = user?.school?.id ?? null
  const mayFillSchoolShelf = Boolean(user?.is_school_admin && schoolId)

  const [folders, setFolders] = useState(null)
  const [items, setItems] = useState([])
  const [shared, setShared] = useState([])
  // открытая папка — поза за работой, а не настройка: живёт во вкладке
  const [open, setOpen] = useKept('bookmarks.open', ALL)
  const [query, setQuery] = useKept('bookmarks.query', '')

  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [schoolDraft, setSchoolDraft] = useState(EMPTY_DRAFT)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ title: '', note: '', folder: '' })
  const [folderDraft, setFolderDraft] = useState('')
  const [renaming, setRenaming] = useState(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [over, setOver] = useState(null)
  const fileInput = useRef(null)
  const schoolFileInput = useRef(null)

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
        fetchBookmarkFolders(),
        fetchBookmarks(user.id),
        schoolId ? fetchSchoolShelf(schoolId) : Promise.resolve([]),
      ])
        .then(([shelves, mine, school]) => {
          setFolders(shelves)
          setItems(mine)
          setShared(school)
        })
        .catch(handleError),
    [handleError, schoolId, user.id],
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

  const matches = useCallback(
    (item) => {
      const needle = query.trim().toLowerCase()
      return [item.title, item.note, item.url]
        .filter(Boolean)
        .some((text) => text.toLowerCase().includes(needle))
    },
    [query],
  )

  const shown = useMemo(() => {
    if (searching) return items.filter(matches)
    if (open === ALL) return items
    if (open === LOOSE) return items.filter((item) => !item.bookmark_folder)
    return items.filter((item) => item.bookmark_folder === open)
  }, [items, matches, open, searching])

  /* Полка школы поиском сужается тоже: искать «бланк» и не найти школьный
     бланк, лежащий на экране выше, — ровно та неожиданность, из-за которой
     поиску перестают верить. */
  const shownShared = useMemo(
    () => (searching ? shared.filter(matches) : shared),
    [matches, searching, shared],
  )

  const countIn = (folder) =>
    items.filter((item) => item.bookmark_folder === folder).length

  // --- заведение ---

  const attach = async (files, { school = false } = {}) => {
    if (!files.length) return
    const note = (school ? schoolDraft : draft).note.trim()

    setBusy(true)
    setError(null)
    try {
      for (const file of files) {
        await uploadAttachment({
          ...(school
            ? { schoolShelf: schoolId }
            : { bookmarkOwner: user.id, bookmarkFolder: folderId ?? undefined }),
          file,
          // приписка, набранная до выбора файла, относится к нему: человек
          // объясняет, зачем несёт файл, а не пишет отдельную записку.
          // Название не шлём вовсе — им станет имя файла
          note,
        })
      }
      ;(school ? setSchoolDraft : setDraft)(EMPTY_DRAFT)
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
  const submit = (school) => async (event) => {
    event.preventDefault()
    const current = school ? schoolDraft : draft
    const what = current.what.trim()
    if (!what) return

    const url = looksLikeUrl(what) ? what : ''
    const title = url ? current.title.trim() || url : what

    setBusy(true)
    setError(null)
    try {
      if (school) {
        await addSchoolShelfItem({
          school: schoolId,
          url,
          title,
          note: current.note.trim(),
        })
        setSchoolDraft(EMPTY_DRAFT)
      } else {
        await addBookmark({
          owner: user.id,
          folder: folderId,
          url,
          title,
          note: current.note.trim(),
        })
        setDraft(EMPTY_DRAFT)
      }
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

  const saveEdit = (mine) => async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await updateBookmark(editing, {
        title: form.title.trim(),
        note: form.note,
        // папка — принадлежность личного стола: у общей полки её нет вовсе,
        // и слать пустое поле значило бы просить сервер о невозможном
        ...(mine
          ? // пустая строка селекта — это «на виду», то есть `null`, а не
            // «поле не трогали»
            { folder: form.folder === '' ? null : Number(form.folder) }
          : {}),
      })
      setEditing(null)
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (item, { mine }) => {
    const question = mine ? 'bookmarks.removeItem' : 'bookmarks.removeShared'
    if (!window.confirm(t(question, { title: item.title }))) return

    setBusy(true)
    setError(null)
    try {
      await deleteAttachment(item.id)
      const drop = (rows) => rows.filter((row) => row.id !== item.id)
      if (mine) setItems(drop)
      else setShared(drop)
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

  /**
   * Строка полки — одна на обе, и различий у неё ровно два.
   *
   * `mine` решает, показывать ли папку (у общей полки папок нет) и кому
   * доступны кнопки: своё правит хозяин, общее — администратор. Всё
   * остальное — значок, название, размер, приписка — у них общее, и
   * общим должно остаться: две похожие строки расходятся в первой же правке.
   */
  const itemRow = (item, { mine }) => {
    const size = formatSize(item.size)
    const mayEdit = mine || mayFillSchoolShelf

    if (editing === item.id) {
      return (
        <li key={item.id} className="attachment shelf-item editing">
          <form className="shelf-edit" onSubmit={saveEdit(mine)}>
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
              {mine && (
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
              )}
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
        {mine && (searching || open === ALL) && item.bookmark_folder && (
          <span className="badge">{folderName(item.bookmark_folder)}</span>
        )}

        {mayEdit && (
          <>
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
              onClick={() => remove(item, { mine })}
            >
              ✕
            </button>
          </>
        )}

        {item.note && <p className="note">{item.note}</p>}
      </li>
    )
  }

  /**
   * Форма заведения — одна на обе полки, с разными черновиками.
   *
   * Зона перетаскивания стоит первой и она же кнопка выбора: тащить умеют не
   * все и не везде, а нажать — везде.
   */
  const addBlock = ({ school }) => {
    const current = school ? schoolDraft : draft
    const set = school ? setSchoolDraft : setDraft
    const input = school ? schoolFileInput : fileInput
    const zone = school ? 'school' : 'mine'

    return (
      <>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          aria-label={t(school ? 'bookmarks.addSchoolFile' : 'bookmarks.addFile')}
          onChange={(event) => {
            attach([...event.target.files], { school })
            event.target.value = ''
          }}
        />

        <button
          type="button"
          className={over === zone ? 'dropzone over' : 'dropzone'}
          disabled={busy}
          onClick={() => input.current.click()}
          onDragOver={(event) => {
            event.preventDefault()
            setOver(zone)
          }}
          onDragLeave={() => setOver(null)}
          onDrop={(event) => {
            event.preventDefault()
            setOver(null)
            attach([...(event.dataTransfer?.files ?? [])], { school })
          }}
        >
          {t('bookmarks.dropHere')}
        </button>

        <form className="shelf-add" onSubmit={submit(school)}>
          <div className="row">
            <input
              value={current.what}
              maxLength={200}
              placeholder={t('bookmarks.whatPlaceholder')}
              aria-label={t(school ? 'bookmarks.whatSchool' : 'bookmarks.what')}
              onChange={(event) => set({ ...current, what: event.target.value })}
            />
            {looksLikeUrl(current.what) && (
              <input
                value={current.title}
                maxLength={200}
                placeholder={t('bookmarks.linkTitle')}
                aria-label={t('bookmarks.linkTitle')}
                onChange={(event) => set({ ...current, title: event.target.value })}
              />
            )}
            <button type="submit" disabled={busy || !current.what.trim()}>
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
            value={current.note}
            maxLength={2000}
            placeholder={t('bookmarks.notePlaceholder')}
            aria-label={t('bookmarks.note')}
            onChange={(event) => set({ ...current, note: event.target.value })}
          />
        </form>
      </>
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

      {/*
        Полка школы стоит **над** личной, и порядок тут содержательный.

        Кладут туда то, что нужно всем и сегодня: бланк, регламент, адрес
        журнала. Внизу страницы это читалось бы как приписка, а смысл её
        ровно обратный — «сначала посмотри сюда».

        Пустую полку сотруднику не показываем вовсе: пустая карточка с
        заголовком обещает содержимое, которого нет. Администратору
        показываем — ему её наполнять.
      */}
      {(shownShared.length > 0 || mayFillSchoolShelf) && (
        <section className="panel school-shelf">
          <h2>{t('bookmarks.fromSchool')}</h2>
          <p className="hint">
            {t(mayFillSchoolShelf ? 'bookmarks.schoolLeadAdmin' : 'bookmarks.schoolLead')}
          </p>

          {shownShared.length > 0 && (
            <ul className="attachments">
              {shownShared.map((item) => itemRow(item, { mine: false }))}
            </ul>
          )}

          {shownShared.length === 0 && searching && (
            <p className="hint">{t('bookmarks.empty.found')}</p>
          )}

          {mayFillSchoolShelf && addBlock({ school: true })}
        </section>
      )}

      {/* Заголовок «Моё» нужен ровно тогда, когда выше есть чужое: без
          школьной полки страница и так вся про своё, и подпись читалась бы
          повтором названия. */}
      {(shownShared.length > 0 || mayFillSchoolShelf) && (
        <h2 className="shelf-heading">{t('bookmarks.mine')}</h2>
      )}

      <div className="shelf-grid">
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

          {shown.length > 0 && (
            <ul className="attachments">
              {shown.map((item) => itemRow(item, { mine: true }))}
            </ul>
          )}

          {shown.length === 0 && (
            <EmptyState title={t('bookmarks.empty.title')}>
              {searching ? t('bookmarks.empty.found') : t('bookmarks.empty.shelf')}
            </EmptyState>
          )}

          {/* Заводить можно и во время поиска, но кладётся оно **не туда,
              что нашлось**: поиск — это способ дойти до вещи, а не место.
              Поэтому форма показывает, куда именно ляжет новое. */}
          {addBlock({ school: false })}

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
