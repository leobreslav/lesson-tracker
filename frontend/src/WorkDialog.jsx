import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import MarkdownField from './MarkdownField'
import Modal from './Modal'
import {
  deleteAttachment,
  fetchGradingSystems,
  fetchWorkImpact,
  openAttachment,
  uploadAttachment,
} from './api'
import { fromLocalInput, toLocalInput } from './dates'
import { formatSize, iconFor } from './fileKind'

/**
 * Настройки работы: название, окно времени, попытки, показ отметки.
 *
 * Черновика здесь нет и быть не должно — работа скрыта от учеников, пока
 * окно не открылось, и это единственный ответ на вопрос «видно ли её».
 * Поэтому даты обязательны: их не отложить «на потом», они и есть решение.
 *
 * У открытой работы окно правки называет цену: «сейчас решают N человек,
 * дано M ответов». Не запрещает — запрет здесь дороже ошибки, опечатку в
 * условии находят посреди урока, — но и молчать нельзя: правка, сделанная
 * вслепую, ломает то, что люди пишут прямо сейчас.
 *
 * **Задание пишется здесь целиком, и это не «пояснения на всякий случай».**
 * Позадачная структура — путь для тех, кому нужна проверка по ячейкам; тот,
 * кому она не нужна, пишет условие текстом в одно поле, а решения получает
 * фотографиями в саму работу. Оба пути законны, и текст в них один и тот же:
 * его видит ученик над задачами и видит учитель — там же.
 *
 * Отсюда две вещи, которых у формы раньше не было: картинка в текст (Ctrl+V,
 * тем же полем, что содержание урока) и файлы, приложенные к работе.
 *
 * **Работа заводится по требованию.** Приложить файл можно только к тому,
 * что уже есть строкой в базе, а пишут задание в окне **создания**, где
 * работы ещё нет. Поэтому первая вставка картинки или первый файл сохраняют
 * работу — с тем, что уже набрано, — и окно продолжает править её же. Тот же
 * приём, что у оценки ученика: строка «работа и ученик» там заводится ровно
 * так же, первым же скан-файлом.
 *
 * Цена названа прямо: до сохранения нужны название и даты, и пока их нет,
 * файл не берётся, а окно говорит почему. Молча проглоченный файл — худший
 * из исходов: человек уверен, что приложил.
 */
export default function WorkDialog({
  work,
  courseId,
  slot,
  homework = false,
  busy,
  onSubmit,
  // завести работу прямо сейчас, если её ещё нет: возвращает сохранённую.
  // Нужен ровно затем, чтобы было к чему прикладывать
  onEnsure,
  onClose,
}) {
  const { t } = useTranslation()
  // `slot` — занятие, с которого работу заводят. Ничего, кроме привязки, он
  // не подставляет: подставленный текст из плана здесь уже был и оказался не
  // нужен — домашнее задание и так написано в плане и видно на уроке
  // `homework` задаётся **разделом**, из которого нажали, а не галочкой в
  // форме: классификация — наше слово, а человек знает, что он сейчас
  // задаёт. Тот же довод, по которому «дополнительный урок» в своё время
  // оказался плохим вопросом
  const [systems, setSystems] = useState([])
  const [form, setForm] = useState(() => ({
    ...initial(work),
    ...(slot ? { slot } : {}),
    ...(homework ? { is_homework: true } : {}),
  }))
  const [impact, setImpact] = useState(null)
  // приложенное к заданию. Приезжает вместе с работой (`files` у неё же) и
  // дальше правится здесь: список меняет только это окно, и спрашивать
  // сервер после каждой правки значило бы спрашивать его о том, что мы
  // только что ему и сказали
  const [files, setFiles] = useState(() => work?.files ?? [])
  const [attaching, setAttaching] = useState(false)
  const [fileError, setFileError] = useState(null)
  const chooseFile = useRef(null)
  // id уже заведённой работы. Ссылкой, а не состоянием: между заведением и
  // следующей строкой той же функции перерисовки не будет, а без свежего id
  // вторая картинка пачки завела бы вторую работу
  const saved = useRef(work?.id ?? null)

  /* Список систем школы: показываются только разрешённые — сервер их и не
     отдаёт другими, а форма не должна предлагать то, чего он не примет. */
  useEffect(() => {
    let alive = true
    fetchGradingSystems()
      .then((answer) => alive && setSystems(answer.systems.filter((one) => one.is_allowed)))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!work) return undefined

    let current = true
    fetchWorkImpact(work.id)
      .then((result) => current && setImpact(result))
      .catch(() => current && setImpact(null))

    return () => {
      current = false
    }
  }, [work])

  const change = (field) => (event) => {
    const value =
      event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((current) => ({ ...current, [field]: value }))
  }

  const fields = () => ({
    course: courseId,
    slot: form.slot ?? null,
    title: form.title.trim(),
    description: form.description,
    opens_at: fromLocalInput(form.opens_at),
    closes_at: fromLocalInput(form.closes_at),
    attempts: form.limited ? Number(form.attempts) : null,
    show_result: form.show_result,
    is_homework: form.is_homework ?? false,
    is_summative: form.is_summative ?? false,
    grading_system: form.grading_system ?? null,
  })

  const submit = (event) => {
    event.preventDefault()
    if (busy || !ready(form)) return

    onSubmit(fields())
  }

  /**
   * Работа, к которой можно что-то приложить, — заведённая при надобности.
   *
   * Отказ здесь исключением, а не тихим `null`: и вставка картинки, и выбор
   * файла показывают его строкой ошибки, и человек видит, чего не хватает,
   * вместо файла, который «как будто приложился».
   */
  const ensureWork = async () => {
    if (saved.current) return saved.current
    if (!ready(form)) throw new Error(t('works.saveBeforeFiles'))

    const created = await onEnsure(fields())
    saved.current = created.id
    return created.id
  }

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
    <Modal onClose={onClose} title={t(work ? 'works.edit' : 'works.add')}>
      <form onSubmit={submit}>

        {impact?.answers > 0 && (
          <p className="hint warning">
            {t('works.impact', {
              answers: impact.answers,
              students: impact.students,
            })}
          </p>
        )}

        <label className="field-with-hint">
          {t('works.workTitle')}
          <input
            autoFocus
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
        <MarkdownField
          value={form.description}
          onChange={(text) => setForm((current) => ({ ...current, description: text }))}
          rows={4}
          label={t('works.description')}
          ensureOwner={async () => ({ work: await ensureWork() })}
          disabled={busy}
        />
        <Hint short={t('works.descriptionHint')} more={t('works.descriptionHintMore')} />

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

        <div className="row">
          <label className="field-with-hint">
            {t('works.opensAt')}
            <input
              type="datetime-local"
              value={form.opens_at}
              onChange={change('opens_at')}
            />
          </label>
          <label className="field-with-hint">
            {t('works.closesAt')}
            <input
              type="datetime-local"
              value={form.closes_at}
              onChange={change('closes_at')}
            />
          </label>
        </div>
        {/* Окно решает не «видно ли работу», а «принимаются ли решения», и
            это две разные вещи. Строка обещала первое — «ученик видит работу
            только пока окно открыто», — а на деле после закрытия у него
            остаётся всё: условия, свои ответы, баллы и переписка с учителем
            по задаче (треды окна не знают вовсе, право там по участию).
            Пропадает ровно одно — возможность прислать новое решение */}
        <Hint short={t('works.windowHint')} more={t('works.windowHintMore')} />

        {/* Система оценивания — решение учителя, на каждой работе своё:
            маленькая проверочная по пятибалльной рядом с контрольной по MYP
            это обычное дело. Администратор только ограничивает список. */}
        <label className="field">
          <span>{t('grading.system')}</span>
          <select
            value={form.grading_system ?? ''}
            onChange={(event) =>
              setForm({
                ...form,
                grading_system: event.target.value ? Number(event.target.value) : null,
              })
            }
          >
            <option value="">{t('grading.noSystem')}</option>
            {systems.map((system) => (
              <option key={system.id} value={system.id}>
                {system.name}
              </option>
            ))}
          </select>
        </label>
        {/* пояснение нужно самому первому пункту списка: «Только баллы, без
            отметки» — это отказ от системы, и по подписи не видно, что при
            этом остаётся.

            Развёрнутого под «?» здесь больше нет, и снято оно по просьбе:
            оно пересказывало устройство порогов, то есть отвечало на вопрос,
            которого в этой форме никто не задаёт, — пороги задаёт школа в
            своём справочнике. А главное, что про них стоило бы сказать, в
            форме про работу не помещается вовсе: **итог ставит учитель**.
            Что бы система ни вывела из баллов, его отметка сильнее, и живёт
            это правило там, где отметку и ставят, — в окне работы ученика */}
        <p className="hint">{t('grading.systemHint')}</p>

        {/* формативную оценивают как придётся, и в итог она не идёт */}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.is_summative}
            onChange={change('is_summative')}
          />
          {t('works.summative')}
        </label>
        <p className="hint">{t('works.summativeHint')}</p>

        {/* попытки — про работу целиком, а не про отдельный вопрос: чекбокса
            «на бумаге» тут больше нет, и прятать эту строку стало не по чему.
            Работа, все ячейки которой пишут на бумаге, попыток не тратит, и
            число в них ничего не портит.

            Ряд по центру (`middle`), а не по низу: умолчание `flex-end`
            верно для ряда полей с подписями сверху, а здесь рядом стоят
            голый чекбокс ростом со строку и поле ростом с контрол — по
            нижнему краю подпись прибивало к донышку поля, и она читалась
            не как заголовок этого числа, а как что-то лежащее под ним */}
        <div className="row middle">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.limited}
              onChange={change('limited')}
            />
            {t('works.limited')}
          </label>
          {form.limited && (
            <input
              type="number"
              min={1}
              max={20}
              value={form.attempts}
              aria-label={t('works.attempts')}
              onChange={change('attempts')}
            />
          )}
        </div>
        {/* «Один: ученик отправляет…» читалось как начало фразы, а не как
            пример: число в поле и число в тексте связывались не сразу.
            Теперь оба случая названы одинаково — «Стоит 1 — …», «Стоит 3 — …» */}
        <Hint short={t('works.attemptsHint')} more={t('works.attemptsHintMore')} />

        {/* «отметка» — слово из школьного обихода, и в форме оно ничего не
            называет. Скрывает флажок не «верно/неверно», а **баллы**: балл за
            каждую задачу, итоговую отметку за работу и комментарий учителя —
            всё разом (`show_result` у модели, `services.mark_for`). Первая
            версия подсказки говорила про вердикт, и это осталось от времён,
            когда вердикт был галочкой; баллом он стал давно */}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.show_result}
            onChange={change('show_result')}
          />
          {t('works.showResult')}
        </label>
        <Hint
          short={t('works.showResultHint')}
          more={t('works.showResultHintMore')}
        />

        <div className="actions">
          <button type="submit" disabled={busy || !ready(form)}>
            {t('common.save')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Новая работа открывается завтра на неделю: правится, но решать не надо. */
function initial(work) {
  if (work) {
    return {
      title: work.title,
      opens_at: toLocalInput(work.opens_at),
      closes_at: toLocalInput(work.closes_at),
      limited: work.attempts !== null,
      attempts: work.attempts ?? 1,
      show_result: work.show_result,
      is_summative: work.is_summative ?? false,
      grading_system: work.grading_system ?? null,
      description: work.description ?? '',
      slot: work.slot ?? null,
      is_homework: work.is_homework ?? false,
    }
  }

  const day = 24 * 60 * 60 * 1000
  const now = Date.now()

  return {
    title: '',
    opens_at: toLocalInput(new Date(now + day).toISOString()),
    closes_at: toLocalInput(new Date(now + 8 * day).toISOString()),
    limited: true,
    attempts: 1,
    show_result: true,
    is_summative: false,
    grading_system: null,
    description: '',
    slot: null,
  }
}

const ready = (form) =>
  Boolean(form.title.trim() && form.opens_at && form.closes_at)
