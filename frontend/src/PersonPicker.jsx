import { useId } from 'react'

/**
 * Выбор человека или курса с поиском по мере ввода.
 *
 * Обычный `<select>` перестаёт работать раньше, чем кажется: в школе
 * бывает несколько десятков учителей, и найти нужного в схлопнутом списке
 * можно только пролистав его глазами. Здесь то же самое, но с фильтром:
 * начали печатать имя или адрес — остались подходящие.
 *
 * Внутри — родной `<datalist>`, а не свой выпадающий список, и это
 * сознательно. Он фильтрует по подстроке сам, ходит с клавиатуры сам,
 * читалке объявляется сам и на телефоне открывается тем, чем этот телефон
 * открывает списки. Свой список пришлось бы учить всему этому заново, и
 * заметно это стало бы не сразу, а на первом же человеке, который ходит
 * по табу.
 *
 * Цена одна и названа прямо: `datalist` отдаёт **строку**, а не id.
 * Поэтому подпись обязана быть однозначной — имя вместе с адресом, — а
 * найденного по ней возвращает `matchItem`. Разрешает строку в id
 * вызывающий, а не сам пикер: иначе внутри пришлось бы держать вторую
 * копию состояния и следить, чтобы она не спорила с внешней. Такая пара
 * («печатаю» против «выбрано») расходится на первом же наборе, когда
 * человек стёр строку, а выбор остался.
 */
export default function PersonPicker({
  items,
  value,
  onChange,
  label,
  placeholder = '',
  disabled = false,
  describe,
}) {
  const listId = useId()

  return (
    <>
      <input
        className="search"
        list={listId}
        value={value}
        aria-label={label}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id={listId}>
        {items.map((item) => (
          <option key={item.id} value={describe(item)} />
        ))}
      </datalist>
    </>
  )
}

/** Кого выбрали — по строке, которую отдал `datalist`. */
export function matchItem(items, text, describe) {
  const wanted = (text ?? '').trim()
  if (!wanted) return null

  return items.find((item) => describe(item) === wanted) ?? null
}

/** Подпись человека: имя и адрес вместе — по обоим и ищут. */
export const describePerson = (person) => {
  const name = [person.first_name, person.last_name].filter(Boolean).join(' ')
  return name ? `${name} · ${person.email}` : person.email
}
