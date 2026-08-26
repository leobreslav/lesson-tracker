import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import WorkContent from './WorkContent'
import WorkSettings from './WorkSettings'
import { fromLocalInput, toLocalInput } from './dates'

/**
 * Форма заведения работы: содержание и настройки одной стопкой.
 *
 * Собрана из тех же двух кусков, что и страница правки, — содержания
 * (`WorkContent`) и настроек (`WorkSettings`), — и в этом весь смысл
 * разделения. При заведении они стоят рядом: даты обязательны, без них
 * работы не завести, а задание тут обычно и не пишут. На странице правки
 * содержание занимает экран, а настройки уходят за кнопку: там уже есть,
 * что править, и главное — текст, который прочтёт класс.
 *
 * Черновика здесь нет и быть не должно — работа скрыта от учеников, пока
 * окно не открылось, и это единственный ответ на вопрос «видно ли её».
 * Поэтому даты обязательны: их не отложить «на потом», они и есть решение.
 *
 * Цену правки — «сейчас решают N человек, дано M ответов» — называет
 * страница, а не эта форма: при заведении работы отвечать на неё ещё
 * некому, и место предупреждению там, где правят живую.
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
export default function WorkForm({
  work,
  courseId,
  slot,
  homework = false,
  busy,
  onSubmit,
  // завести работу прямо сейчас, если её ещё нет: возвращает сохранённую.
  // Нужен ровно затем, чтобы было к чему прикладывать
  onEnsure,
  onCancel,
}) {
  const { t } = useTranslation()
  // `slot` — занятие, с которого работу заводят. Ничего, кроме привязки, он
  // не подставляет: подставленный текст из плана здесь уже был и оказался не
  // нужен — домашнее задание и так написано в плане и видно на уроке
  // `homework` задаётся **разделом**, из которого нажали, а не галочкой в
  // форме: классификация — наше слово, а человек знает, что он сейчас
  // задаёт. Тот же довод, по которому «дополнительный урок» в своё время
  // оказался плохим вопросом
  const [form, setForm] = useState(() => ({
    ...initial(work),
    ...(slot ? { slot } : {}),
    ...(homework ? { is_homework: true } : {}),
  }))
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

  return (
    <form onSubmit={submit}>

      {/* Содержание — название, задание и файлы — и настройки стоят
          рядом только здесь, при заведении: даты обязательны, без них
          работы не завести. На странице правки содержание занимает экран,
          а настройки уехали за кнопку (`WorkSettings.jsx`) */}
      <WorkContent
        form={form}
        setForm={setForm}
        ensureWork={ensureWork}
        initialFiles={work?.files ?? []}
        busy={busy}
        autoFocus
      />

      {/* Мелкие поля — окно времени, попытки, показ отметки, итоговая,
          система оценивания — вынесены целиком (`WorkSettings.jsx`). Здесь,
          при заведении, они на месте: даты обязательны, без них работы не
          завести. На странице правки они уехали за кнопку «Настройки» —
          главное там задание, а не четыре флажка */}
      <WorkSettings form={form} setForm={setForm} courseId={courseId} busy={busy} />

      <div className="actions">
        <button type="submit" disabled={busy || !ready(form)}>
          {t('common.save')}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
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
