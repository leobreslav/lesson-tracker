import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'

/**
 * Полка планов — окном, а не разделом.
 *
 * Отдельная страница «Библиотека» была местом, куда заходят просто так:
 * посмотреть чужие планы вне своего курса незачем, а нужны они ровно в один
 * момент — когда набираешь план и хочешь взять готовый. Поэтому полка живёт
 * там же, где план.
 *
 * Вместе со страницей сюда переехало то, чего больше нигде нет: поиск по
 * названию, сужение по предмету и году обучения, просмотр содержимого до
 * того, как брать, и управление своими записями — опубликовать черновик,
 * снять с публикации, удалить. Без последнего снятый с плана шаблон навсегда
 * остался бы черновиком: `from-plan` заводит его неопубликованным, и другой
 * кнопки нет.
 *
 * Список идёт **двумя группами** — мои планы и планы коллег. Галочка «только
 * мои» была вместо них и отвечала на другой вопрос: «спрятать ли чужое», —
 * тогда как спрашивают «где моё». Ответив на первый, человек терял из виду
 * половину полки.
 *
 * Запросов отсюда не уходит ни одного — как и у таблицы плана, всё уезжает
 * наверх колбэками: страница знает про `busy`, ошибки и перечитывание полки.
 */
export default function LibraryDialog({
  templates,
  busy,
  onTake,
  onOpen,
  onEdit,
  onCreate,
  onPublish,
  onDelete,
  onClose,
}) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [subject, setSubject] = useState('')
  const [grade, setGrade] = useState('')
  const [mode, setMode] = useState('replace')
  const [chosen, setChosen] = useState(null)

  /**
   * Что вообще лежит на полке — по **всему** набору, а не по сужённому.
   *
   * Тот же расчёт, что у сужения курсов в `CoursePicker`, и по той же
   * причине: выбранный предмет вычистил бы из соседнего списка все годы,
   * кроме своих, и вернуться к «любому» стало бы нечем.
   */
  const options = useMemo(() => {
    const subjects = [
      ...new Set(templates.map((item) => item.subject_name).filter(Boolean)),
    ].sort((a, b) => a.localeCompare(b))
    const grades = [...new Set(templates.map((item) => item.grade))].sort(
      (a, b) => a - b,
    )
    return { subjects, grades }
  }, [templates])

  /*
   * Предмет и год — селектами, а не совпадением по тексту.
   *
   * Поиск искал сразу по названию и предмету, и это выглядело удобно ровно
   * до первого промаха: «алгебра» находила и «Алгебра 9», и «Повторение
   * алгебры за 8», а «6» не находила шестой класс вовсе — год в подписи
   * стоит, а в полях, по которым искали, его не было. Селект отвечает на
   * вопрос точно и заодно показывает, что на полке вообще есть.
   *
   * Поиск остался, и теперь он про одно — про название.
   */
  const found = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return templates.filter(
      (item) =>
        (!subject || item.subject_name === subject) &&
        (!grade || String(item.grade) === grade) &&
        (!needle || item.title.toLowerCase().includes(needle)),
    )
  }, [templates, query, subject, grade])

  /*
   * Мои планы и планы коллег — двумя списками, а не галочкой «только мои».
   *
   * Галочка отвечала на вопрос «спрятать ли чужое», а спрашивают другое:
   * «где моё». Ответом на первый вопрос человек терял из виду вторую
   * половину полки; ответом на второй — видит обе сразу и знает, какая
   * какая. То же решение, что у групп в селекторе курсов: там тоже разные
   * **роли**, а не свойства записи.
   */
  const groups = [
    { key: 'mine', items: found.filter((item) => item.mine) },
    { key: 'others', items: found.filter((item) => !item.mine) },
  ].filter((group) => group.items.length)

  const line = (item) =>
    t('library.line', {
      subject: item.subject_name,
      grade: item.grade,
      author: item.author_name || '—',
      lessons: t('common.lessonCount', { count: item.lessons }),
    })

  return (
    <Modal className="shelf" onClose={onClose} title={t('plan.importLibrary')}>
      {/*
        «Написать новый» стоит **над** списком и виден даже когда полка
        пуста. Это и есть тот случай, ради которого он заведён: программу
        для класса, который в этом году не ведут, писать было негде вовсе —
        плану нужен был курс, а курса под такую программу нет.
      */}
      <div className="row">
        <button type="button" disabled={busy} onClick={onCreate}>
          {t('plan.shelf.create')}
        </button>
      </div>

      {!templates.length ? (
        <p className="hint">{t('library.empty.hint')}</p>
      ) : (
        <>
          <div className="row">
            <input
              autoFocus
              type="search"
              value={query}
              placeholder={t('library.search')}
              aria-label={t('library.search')}
              onChange={(event) => setQuery(event.target.value)}
            />
            {options.subjects.length > 1 && (
              <select
                className="course-filter"
                value={subject}
                aria-label={t('library.anySubject')}
                onChange={(event) => setSubject(event.target.value)}
              >
                <option value="">{t('library.anySubject')}</option>
                {options.subjects.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            )}
            {options.grades.length > 1 && (
              <select
                className="course-filter"
                value={grade}
                aria-label={t('library.anyGrade')}
                onChange={(event) => setGrade(event.target.value)}
              >
                <option value="">{t('library.anyGrade')}</option>
                {options.grades.map((level) => (
                  <option key={level} value={String(level)}>
                    {t('library.gradeOption', { grade: level })}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* полка показывается целиком: раньше её сужали до предмета
              курса, и найти чужой план по смежному предмету было нельзя,
              а сказать об этом было нечем — теперь сужают селекты */}
          {!found.length ? (
            <p className="hint">{t('library.nothingFound')}</p>
          ) : (
            groups.map(({ key, items }) => (
            <section key={key}>
              {/* заголовок группы всегда, даже когда группа одна: «Мои
                  планы» над единственным списком говорит, чей он, а
                  отсутствие заголовка не говорит ничего */}
              <h4 className="shelf-group">{t(`library.groups.${key}`)}</h4>
              <ul className="class-list template-list">
              {items.map((item) => (
                <li key={item.id} className={item.id === chosen ? 'chosen' : ''}>
                  <button
                    type="button"
                    className="link name"
                    aria-pressed={item.id === chosen}
                    onClick={() => setChosen(item.id)}
                  >
                    {item.title}
                  </button>
                  <span className="hint">{line(item)}</span>
                  {/* Метки — одной ячейкой: каждая прибита к одной клетке
                      сетки, и вторая легла бы поверх первой. Метка сейчас
                      осталась одна — «черновик», — но ячейка своя, иначе
                      соседняя колонка прыгала бы между строками */}
                  <span className="badges">
                    {!item.is_published && (
                      <span className="badge">{t('library.draft')}</span>
                    )}
                  </span>

                  {/* действия одной ячейкой: их от одного до трёх, и в
                      отдельных колонках сетка разъезжалась бы построчно */}
                  <span className="row-actions">
                    <button
                      type="button"
                      className="link"
                      disabled={busy}
                      onClick={() => onOpen(item)}
                    >
                      {t('library.look')}
                    </button>
                    {/* «Править» — у своего, и ведёт оно на тот же экран
                        плана, каким правят курс. Полка перестала быть только
                        снимком чужой работы: программу пишут и для класса,
                        который в этом году не ведут */}
                    {item.can_edit && (
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        onClick={() => onEdit(item)}
                      >
                        {t('plan.shelf.edit')}
                      </button>
                    )}
                    {item.can_edit && (
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        onClick={() => onPublish(item, !item.is_published)}
                      >
                        {t(item.is_published ? 'library.unpublish' : 'library.publish')}
                      </button>
                    )}
                    {item.can_delete && (
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        title={t('common.delete')}
                        onClick={() => onDelete(item)}
                      >
                        ✕
                      </button>
                    )}
                  </span>
                </li>
              ))}
              </ul>
            </section>
            ))
          )}

          <div className="row">
            <label className="checkbox">
              <input
                type="radio"
                name="library-mode"
                checked={mode === 'replace'}
                onChange={() => setMode('replace')}
              />
              {t('csv.modeReplace')}
            </label>
            <label className="checkbox">
              <input
                type="radio"
                name="library-mode"
                checked={mode === 'append'}
                onChange={() => setMode('append')}
              />
              {t('csv.modeAppend')}
            </label>
          </div>

          {mode === 'replace' && <p className="error">{t('csv.replaceWarning')}</p>}
          <p className="hint">{t('library.once')}</p>
          {/* иначе конструктор не находится: кнопка называется «Посмотреть»,
              и по ней не видно, что оттуда можно взять часть */}
          <p className="hint">{t('library.partHint')}</p>
        </>
      )}

      <div className="actions">
        <button
          type="button"
          disabled={busy || !chosen}
          onClick={() => onTake({ template: chosen, mode })}
        >
          {t('library.use')}
        </button>
        <button type="button" className="secondary" onClick={onClose}>
          {t('common.cancel')}
        </button>
      </div>
    </Modal>
  )
}

/**
 * Что лежит внутри какого блока — по плоскому списку строк.
 *
 * Шаблон плоский (`is_header` вместо вложенности), поэтому блок здесь не
 * узел, а отрезок: заголовок и всё до следующего заголовка. Считается один
 * раз на шаблон — выбор блока целиком нужен на каждое нажатие по нему.
 */
function blocksOf(rows) {
  const blocks = new Map()
  let header = null

  for (const row of rows) {
    if (row.is_header) {
      header = row.id
      blocks.set(header, [])
      continue
    }
    if (header !== null) blocks.get(header).push(row.id)
  }

  return blocks
}

/**
 * Содержимое шаблона: посмотреть — и взять целиком или по частям.
 *
 * Курс собирают конструктором. «Возьму отсюда тему про векторы, а оттуда
 * два урока» — обычная просьба, и до сих пор ответом на неё было «возьмите
 * план целиком и удалите лишнее»: в плане на сотню уроков это работа на
 * полчаса, после которой отменять нечего.
 *
 * Поэтому у каждой строки флажок, а у заголовка он берёт блок целиком:
 * блоками и мыслят, а десять флажков подряд ради одной темы — та же работа
 * руками, только мельче.
 *
 * Выбранное **дописывается в конец** плана, а не заменяет его: конструктор
 * складывает, а не начинает заново. Взять план целиком по-прежнему можно
 * соседней кнопкой, и она по-прежнему заменяет.
 *
 * Строки тут только показывают: правят их на экране плана — своего шаблона
 * прямо в библиотеке, чужого никак.
 */
export function TemplateView({ template, busy, onUse, onClose }) {
  const { t } = useTranslation()
  const [picked, setPicked] = useState(() => new Set())
  const blocks = useMemo(() => blocksOf(template.rows), [template.rows])
  let number = 0

  /** Нажатие по строке: у заголовка — вместе с блоком, у урока — по себе. */
  const toggle = (row) =>
    setPicked((current) => {
      const next = new Set(current)
      const family = [row.id, ...(blocks.get(row.id) ?? [])]
      // блок, взятый не целиком, добирается до целого: так нажатие по
      // заголовку всегда значит «весь блок», а не «наоборот тому, что есть»
      const whole = family.every((id) => next.has(id))

      for (const id of family) {
        if (whole) next.delete(id)
        else next.add(id)
      }

      return next
    })

  const lessons = template.rows.filter(
    (row) => !row.is_header && picked.has(row.id),
  ).length

  return (
    <Modal onClose={onClose} title={template.title}>
      <p className="hint">
        {t('library.line', {
          subject: template.subject_name,
          grade: template.grade,
          author: template.author_name || '—',
          lessons: t('common.lessonCount', { count: template.lessons }),
        })}
      </p>
      {template.description && <p>{template.description}</p>}
      <p className="hint">{t('library.pickHint')}</p>

      <ul className="plan-preview pickable">
        {template.rows.map((row) => {
          if (!row.is_header) number += 1
          return (
            <li key={row.id} className={row.is_header ? 'section' : 'lesson'}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  data-row={row.id}
                  checked={picked.has(row.id)}
                  aria-label={row.title}
                  onChange={() => toggle(row)}
                />
                {row.is_header ? (
                  <strong>{row.title}</strong>
                ) : (
                  <>
                    <span className="plan-number">{number}.</span> {row.title}
                  </>
                )}
              </label>
              {row.note && <span className="hint">{row.note}</span>}
            </li>
          )
        })}
      </ul>

      <div className="actions wrap">
        <button
          type="button"
          disabled={busy || !picked.size}
          onClick={() => onUse({ rows: [...picked], mode: 'append' })}
        >
          {t('library.takePicked', { count: lessons })}
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={() => onUse()}>
          {t('library.use')}
        </button>
      </div>
    </Modal>
  )
}
