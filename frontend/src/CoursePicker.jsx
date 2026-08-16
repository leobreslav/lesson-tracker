import { useTranslation } from 'react-i18next'

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
}) {
  const { t } = useTranslation()

  if (!courses?.length) return null

  if (courses.length === 1) {
    return <span className="course-picked">{label(courses[0])}</span>
  }

  return (
    <select
      className="course-picker"
      value={value ?? ''}
      aria-label={t('plan.courseLabel')}
      onChange={(event) => onChange(Number(event.target.value))}
    >
      {groups.length === 0
        ? courses.map((item) => (
            <option key={item.id} value={item.id}>
              {label(item)}
            </option>
          ))
        : groups.map(({ key, items }) => (
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
}
