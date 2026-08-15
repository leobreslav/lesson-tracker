import { useState } from 'react'
import { remember, remembered } from './remember'

/**
 * Карточка, которая сворачивается. Заголовок и есть переключатель.
 *
 * Заведена ради страницы урока: разделов там пять, и держать пять
 * собственных реализаций свёртки значило бы получить пять слегка разных.
 *
 * **Состояние запоминается** (`remember.js`), и это пересмотр решения,
 * принятого, когда сворачивался один только журнал. Тогда казалось, что
 * свёрнутость — свойство занятия: на новом уроке журнал снова пуст, значит
 * снова закрыт. На пяти блоках видно, что это неправда: закрыть или открыть
 * раздел — привычка человека, а не состояние урока, и учитель, отмечающий
 * посещаемость каждый день, иначе открывал бы её пять раз в день.
 *
 * Умолчание при этом остаётся за экраном: `openByDefault` действует, пока
 * человек ничего не решил сам.
 *
 * `note` — то, что видно **не открывая**: «отмечено 3 из 14». Без него
 * свёрнутый блок означал бы «не знаю, что там», и открывать пришлось бы
 * каждый.
 *
 * `actions` стоят в шапке **рядом** с переключателем, а не внутри него:
 * кнопка внутри кнопки разметкой не разрешена, да и нажатие на «Новая
 * работа» не должно попутно сворачивать раздел.
 */
export default function Collapsible({
  name,
  title,
  note = null,
  actions = null,
  openByDefault = true,
  children,
}) {
  const key = `lesson.${name}`
  const [open, setOpen] = useState(() => remembered(key, openByDefault))

  const toggle = () => {
    setOpen(!open)
    remember(key, !open)
  }

  return (
    <section className="panel" data-block={name}>
      <div className="panel-head spread">
        <button
          type="button"
          className="panel-toggle"
          aria-expanded={open}
          onClick={toggle}
        >
          <span className="caret">{open ? '▾' : '▸'}</span>
          <span className="panel-title">{title}</span>
          {note !== null && <span className="hint">{note}</span>}
        </button>
        {actions}
      </div>

      {open && children}
    </section>
  )
}
