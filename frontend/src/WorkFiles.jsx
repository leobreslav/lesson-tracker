import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  deleteAttachment,
  openAttachment,
  setAttachmentVisibility,
  uploadAttachment,
} from './api'
import { formatSize, iconFor } from './fileKind'

/**
 * Файлы работы: условия одним pdf'ом, бланк для печати, разбор.
 *
 * Своим блоком, а не куском содержания, потому что мест у него два и стоят
 * они по-разному. В окне заведения (с урока и из журнала) файлы идут сразу
 * под текстом задания: прикладывают их в тот же заход, что и пишут. А на
 * странице правки между текстом и файлами встали **задачи** — вторая
 * половина той же работы, — и файлы уехали под них.
 *
 * Порознь блок и его состояние жить не могут: список, флажок «кому достанется
 * то, что положат», и три обработчика — одно целое, и разрезать их по двум
 * экранам значило бы завести две копии.
 *
 * Файлы — строки в базе, поэтому применяются сразу, не дожидаясь
 * «Сохранить»: файл, ждущий кнопки, — это загрузка, которая тихо не
 * случилась.
 *
 * Ссылок и записей тут нет намеренно — в отличие от материалов урока.
 * Материал урока это то, чем пользуется учитель («принести линейку»); здесь
 * лежит то, что открывают файлом, и «запись без цели» была бы строкой, на
 * которую нечего нажать.
 *
 * А вот **кому** это открывают, решает каждая строка сама: условия и бланк —
 * классу, ответы и разбор — только учителю. Прежде видно было всё и всем,
 * поэтому ответы к контрольной приложить было просто некуда.
 */
export default function WorkFiles({
  // работа, к которой можно прикладывать. При заведении её ещё нет, и
  // первый же файл заводит её — см. `WorkForm`
  ensureWork,
  initialFiles = [],
  busy = false,
}) {
  const { t } = useTranslation()

  const [files, setFiles] = useState(initialFiles)
  const [attaching, setAttaching] = useState(false)
  const [fileError, setFileError] = useState(null)
  const chooseFile = useRef(null)
  /*
   * Кому достанутся файлы, которые сейчас положат.
   *
   * Спрашивается **до** загрузки, и это не придирка к порядку. Ответы к
   * контрольной, приложенные видимыми и спрятанные секундой позже, эту
   * секунду открыты всему классу — а класс смотрит на работу как раз тогда,
   * когда учитель её собирает. Передумать можно и после, строкой в списке;
   * начать с открытого нельзя.
   *
   * Умолчание — «классу», потому что ради этого вложения к работе и заведены:
   * условия, бланк, разбор после урока. Спрятанное — случай нередкий, но
   * второй.
   */
  const [hidden, setHidden] = useState(false)

  const attach = async (chosen) => {
    if (!chosen.length) return

    setAttaching(true)
    setFileError(null)
    try {
      const id = await ensureWork()
      for (const file of chosen) {
        const added = await uploadAttachment({ work: id, file, staffOnly: hidden })
        setFiles((current) => [...current, added])
      }
    } catch (failure) {
      setFileError(failure.message)
    } finally {
      setAttaching(false)
    }
  }

  /* Передумать: показать классу спрятанное или спрятать показанное. */
  const flipVisibility = async (item) => {
    setAttaching(true)
    setFileError(null)
    try {
      const saved = await setAttachmentVisibility(item.id, !item.staff_only)
      setFiles((current) =>
        current.map((one) => (one.id === item.id ? { ...one, ...saved } : one)),
      )
    } catch (failure) {
      setFileError(failure.message)
    } finally {
      setAttaching(false)
    }
  }

  const removeFile = async (item) => {
    if (!window.confirm(t('lesson.removeAttachment', { title: item.title }))) return

    setAttaching(true)
    setFileError(null)
    try {
      await deleteAttachment(item.id)
      setFiles((current) => current.filter((one) => one.id !== item.id))
    } catch (failure) {
      setFileError(failure.message)
    } finally {
      setAttaching(false)
    }
  }

  return (
    <div className="work-field">
        <div className="row middle">
          <span className="field-label">{t('works.files')}</span>
          {files.length > 0 && <span className="hint">{files.length}</span>}
        </div>

        {files.length > 0 && (
          <ul className="attachments">
            {files.map((item) => {
              const size = formatSize(item.size)

              return (
                <li key={item.id} className="attachment">
                  <span className="attachment-icon" aria-hidden="true">
                    {iconFor(item)}
                  </span>
                  <button
                    type="button"
                    className="link title"
                    title={t('lesson.download')}
                    onClick={() => openAttachment(item.id).catch((failure) =>
                      setFileError(failure.message),
                    )}
                  >
                    {item.title}
                  </button>
                  {size && (
                    <span className="hint">
                      {t(`lesson.size.${size.unit}`, { value: size.value })}
                    </span>
                  )}
                  {/* Кому виден этот файл — и тут же способ передумать.
                      Написано состоянием, а не действием («Виден классу», а
                      не «Показать классу»): в списке из пяти строк важнее
                      прочитать одним взглядом, что кому открыто, чем
                      догадаться, что случится по нажатию. Что нажатие
                      переключает, говорит подсказка при наведении. */}
                  <button
                    type="button"
                    className={item.staff_only ? 'link visibility hidden' : 'link visibility'}
                    title={t(item.staff_only ? 'works.showToClass' : 'works.hideFromClass')}
                    disabled={attaching || busy}
                    onClick={() => flipVisibility(item)}
                  >
                    {t(item.staff_only ? 'works.onlyYou' : 'works.seenByClass')}
                  </button>
                  <button
                    type="button"
                    className="link remove"
                    title={t('common.delete')}
                    disabled={attaching || busy}
                    onClick={() => removeFile(item)}
                  >
                    ✕
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {/* Кому достанется то, что положат сейчас. Стоит над зоной, а не под
            ней: решение принимается до броска, а прочитанное после — уже не
            решение, а сообщение о случившемся. */}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={hidden}
            disabled={attaching || busy}
            onChange={(event) => setHidden(event.target.checked)}
          />
          {t('works.attachHidden')}
        </label>
        <p className="hint">
          {t(hidden ? 'works.attachHiddenOn' : 'works.attachHiddenOff')}
        </p>

        <input
          ref={chooseFile}
          type="file"
          multiple
          hidden
          aria-label={t('works.addFile')}
          onChange={(event) => {
            attach([...event.target.files])
            event.target.value = ''
          }}
        />
        {/* зона перетаскивания — она же кнопка выбора: тащить умеют не все и
            не везде, а нажать везде. Та же, что в панели урока */}
        <button
          type="button"
          className="dropzone"
          disabled={attaching || busy}
          onClick={() => chooseFile.current.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            attach([...(event.dataTransfer?.files ?? [])])
          }}
        >
          {attaching ? t('works.attaching') : t('works.dropHere')}
        </button>
        {fileError && (
          <p className="error" role="alert">
            {fileError}
          </p>
        )}
      </div>
  )
}
