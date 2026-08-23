import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import MarkdownField from './MarkdownField'
import Rendered from './Markdown'
import { deleteAttachment, openAttachment, uploadAttachment } from './api'
import { formatSize, iconFor } from './fileKind'

/**
 * Содержание работы: название, задание и приложенные к нему файлы.
 *
 * То, ради чего работу заводят, и то, что увидит класс. Стоит отдельно от
 * настроек (`WorkSettings.jsx`) ровно поэтому: там пять полей, которые
 * задают один раз, здесь — текст, который переписывают весь год.
 *
 * **Просмотр — режим блока, а не второе поле рядом.** Задание это Markdown
 * с формулами и картинками, и увидеть его так, как увидит ученик, нужно;
 * но поле и вид, стоящие бок о бок, делят пополам ту самую ширину, ради
 * которой правку и унесли из окна на страницу. Тумблер тот же, что в панели
 * урока и в окне задачи, — один орган на один вопрос во всём приложении.
 *
 * Вид под полем (`MarkdownField`) при этом остаётся и просмотром **не
 * является**: он про расстановку картинок, появляется, только когда они в
 * тексте есть, и правка в нём идёт своим чередом.
 *
 * Файлы — строки в базе, поэтому применяются сразу, не дожидаясь
 * «Сохранить»: файл, ждущий кнопки, — это загрузка, которая тихо не
 * случилась.
 */
export default function WorkContent({
  form,
  setForm,
  // работа, к которой можно прикладывать. При заведении её ещё нет, и
  // первый же файл заводит её — см. `WorkForm`
  ensureWork,
  initialFiles = [],
  busy = false,
  preview = false,
  // на странице задание — главное поле, и мерить его четырьмя строками
  // незачем; в окне заведения четыре и есть верх
  rows = 4,
  // фокус в окне попадает на название сам, а на странице тот же фокус
  // прокрутил бы её мимо заголовка
  autoFocus = false,
}) {
  const { t } = useTranslation()

  const change = (field) => (event) =>
    setForm((current) => ({ ...current, [field]: event.target.value }))

  const [files, setFiles] = useState(initialFiles)
  const [attaching, setAttaching] = useState(false)
  const [fileError, setFileError] = useState(null)
  const chooseFile = useRef(null)

  const attach = async (chosen) => {
    if (!chosen.length) return

    setAttaching(true)
    setFileError(null)
    try {
      const id = await ensureWork()
      for (const file of chosen) {
        const added = await uploadAttachment({ work: id, file })
        setFiles((current) => [...current, added])
      }
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
    <>
      <label className="field-with-hint">
        {t('works.workTitle')}
        <input
          autoFocus={autoFocus}
          value={form.title}
          maxLength={200}
          onChange={change('title')}
        />
      </label>

      {/* Текст задания — то, что увидит ученик над задачами, и то же
          самое видит над ними учитель.

          Прежняя подсказка объясняла его через домашнее задание («у
          домашнего это оно и есть»), и объяснение было неверным дважды:
          домашняя работа ничем, кроме признака, от контрольной не
          отличается, а поле нужно им обеим одинаково. Нужно оно затем,
          чтобы **не заводить задачи**: кто пишет условие текстом, тот
          получает решения фотографиями в саму работу, и это законный
          способ вести работу целиком.

          Поле — такое же, как содержание урока: Markdown с формулами и
          картинка по Ctrl+V. Своего редактора у него нет и не будет — см.
          `MarkdownField.jsx` */}
      <span className="hint">{t('works.description')}</span>
      {preview ? (
        /* Пустое задание в просмотре — это строка «тут пусто», а не пустое
           место: пустое место читается как «не загрузилось», и первый же
           вопрос будет про поломку, а не про ненаписанный текст. */
        form.description.trim() ? (
          <div className="work-brief">
            <Rendered text={form.description} />
          </div>
        ) : (
          <p className="hint">{t('works.noDescription')}</p>
        )
      ) : (
        <>
          <MarkdownField
            value={form.description}
            onChange={(text) => setForm((current) => ({ ...current, description: text }))}
            rows={rows}
            label={t('works.description')}
            ensureOwner={async () => ({ work: await ensureWork() })}
            disabled={busy}
          />
          <Hint short={t('works.descriptionHint')} more={t('works.descriptionHintMore')} />
        </>
      )}

      {/* Файлы работы: условия одним pdf'ом, бланк для печати, разбор.
          Стоят рядом с текстом, а не в отдельном окне, потому что
          прикладывают их в тот же заход, что и пишут задание.

          Ссылок и записей тут нет намеренно — в отличие от материалов
          урока. Материал урока это то, чем пользуется учитель («принести
          линейку»); здесь же всё, что лежит, увидит класс, и «запись без
          цели» была бы строкой, на которую ученику нечего нажать */}
      <div className="row middle">
        <span className="hint">{t('works.files')}</span>
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
    </>
  )
}
