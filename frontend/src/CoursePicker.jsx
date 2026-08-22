import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useKept } from './remember'

/**
 * Каким курсом сейчас занимаемся — в строке заголовка страницы.
 *
 * Чипами это было: по кнопке на курс, выбранная залита синим. На трёх
 * курсах читается прекрасно, а у учителя музыки их пятнадцать — и полтора
 * десятка кнопок занимают две строки над содержимым, ради выбора, который
 * делают раз за заход.
 *
 * Поэтому селект, и стоит он **рядом с заголовком**, а не отдельной полосой
 * под ним: курс это не фильтр к странице, а то, про что она. «Учебный план
 * — 7Б Физика» читается как название, чем оно и является.
 *
 * Один курс — не селект, а просто имя: выбирать не из чего, а сказать, чей
 * это план, всё равно надо.
 *
 * `groups` — разбивка списком `{key, items}`: у методиста в одном селекте
 * лежат три разных вещи, и мешать их нельзя. «Мои курсы» — те, что он ведёт;
 * «Ждут ответа» — чужие планы, присланные на утверждение; «Под надзором» —
 * остальные чужие, за которыми он смотрит. Разделены они `optgroup`'ом, а не
 * значком в подписи: значок читается как свойство курса, а тут разные **роли
 * человека**, и группа говорит об этом прямо.
 */
export default function CoursePicker({
  courses,
  value,
  onChange,
  label = (item) => item.name,
  groups = [],
  narrow = null,
}) {
  const { t } = useTranslation()
  /*
   * Сужение — не состояние страницы, а поза человека за работой: «сегодня
   * я смотрю физику у Петровой». Поэтому оно переживает уход со страницы
   * и возврат назад, но не закрытие вкладки.
   */
  const [filter, setFilter] = useKept(`courses.narrow.${narrow ?? 'none'}`, {
    teacher: '',
    subject: '',
  })

  /**
   * Чьи курсы и по каким предметам вообще лежат в списке.
   *
   * Оба списка считаются по **всему** набору, а не по уже сужённому: иначе
   * выбранный учитель вычистил бы из соседнего селекта все предметы, кроме
   * своих, и вернуться к «любому» стало бы нечем.
   */
  const options = useMemo(() => {
    const distinct = (field) =>
      [...new Set((courses ?? []).map((item) => item[field]).filter(Boolean))].sort(
        (a, b) => a.localeCompare(b),
      )
    return { teachers: distinct('teacher'), subjects: distinct('subjectName') }
  }, [courses])

  /*
   * Фильтры показываются, только когда в списке чужие курсы.
   *
   * У учителя со своими пятнадцатью курсами сужать по учителю нечего — он
   * там один, — а у администратора школы в том же селекте лежат все курсы
   * школы, и их несколько десятков. Поэтому условие про **разных учителей**,
   * а не про длину списка: длинный список своих курсов и так разобран по
   * группам, а чужой длинный разбирать нечем.
   */
  const filtering = Boolean(narrow) && options.teachers.length > 1

  const fits = (item) =>
    // выбранный курс остаётся в списке всегда: это то, про что страница
    // сейчас, и вычистить его фильтром значило бы показать пустой селект
    item.id === value ||
    ((!filter.teacher || item.teacher === filter.teacher) &&
      (!filter.subject || item.subjectName === filter.subject))

  const shown = filtering ? (courses ?? []).filter(fits) : courses ?? []
  const shownGroups = filtering
    ? groups
        .map((group) => ({ ...group, items: group.items.filter(fits) }))
        .filter((group) => group.items.length)
    : groups

  if (!courses?.length) return null

  const select =
    shown.length === 1 && !filtering ? (
      <span className="course-picked">{label(shown[0])}</span>
    ) : (
      <select
        className="course-picker"
        value={value ?? ''}
        aria-label={t('plan.courseLabel')}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {shownGroups.length === 0
          ? shown.map((item) => (
              <option key={item.id} value={item.id}>
                {label(item)}
              </option>
            ))
          : shownGroups.map(({ key, items }) => (
              <optgroup key={key} label={t(`plan.groups.${key}`)}>
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {label(item)}
                  </option>
                ))}
              </optgroup>
            ))}
      </select>
    )

  // один учитель — один селект, ровно как было: обёртка ради пустоты
  // сдвинула бы заголовок на всех остальных страницах
  if (!filtering) return select

  const narrowBy = (field, list, any) => (
    <select
      className="course-filter"
      value={filter[field]}
      aria-label={t(any)}
      onChange={(event) =>
        setFilter((current) => ({ ...current, [field]: event.target.value }))
      }
    >
      <option value="">{t(any)}</option>
      {list.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  )

  return (
    <span className="course-choice">
      {select}
      {narrowBy('teacher', options.teachers, 'plan.filters.anyTeacher')}
      {options.subjects.length > 1 &&
        narrowBy('subject', options.subjects, 'plan.filters.anySubject')}
    </span>
  )
}
