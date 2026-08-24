import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'

/**
 * Кабинеты школы: список, который ведёт администратор.
 *
 * Третий справочник на этой странице, рядом с предметами и параллелями, и
 * устроен он так же — с одной разницей, которая и есть весь смысл: у
 * кабинета два свойства, и оба про то, о чём расписание будет молчать.
 *
 * **Делимый** — это спортзал и актовый зал: несколько занятий разом там
 * норма, и совпадение в них не новость. Запрета на занятость в этой школе
 * нет вовсе (два класса, загнанных в один кабинет, — обычное дело), поэтому
 * остаётся предупреждение; а у предупреждения единственная беда —
 * привыкание. Горящий каждый день спортзал приучил бы отмахиваться и от
 * настоящих совпадений, поэтому про делимый молчат.
 *
 * **Архивный** — закрытый на ремонт или отданный под склад: из выбора в
 * расписании исчез, в истории остался. Удалить его вместо этого нельзя, и
 * это не строгость: «урок шёл в 214» — факт прошедшего дня, и он не
 * перестаёт быть правдой оттого, что кабинета больше нет. Отказ на удаление
 * так и говорит.
 */
export default function RoomsPanel({ rooms, busy, onCreate, onUpdate, onDelete }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  const [editing, setEditing] = useState(null) // {id, value}

  const add = (event) => {
    event.preventDefault()
    const value = name.trim()
    if (!value || busy) return
    onCreate({ name: value, is_shared: shared }).then(() => {
      setName('')
      setShared(false)
    })
  }

  /* Переименование — кликом по названию, как у предмета и параллели рядом:
     одна операция не должна делаться двумя способами на одной странице. */
  const rename = () => {
    if (!editing) return
    const value = editing.value.trim()
    const room = rooms.find((item) => item.id === editing.id)
    setEditing(null)
    if (value && room && value !== room.name) onUpdate(editing.id, { name: value })
  }

  const title = (room) =>
    editing?.id === room.id ? (
      <input
        autoFocus
        value={editing.value}
        maxLength={100}
        aria-label={t('school.rooms.rename')}
        disabled={busy}
        onChange={(event) => setEditing({ ...editing, value: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === 'Enter') rename()
          if (event.key === 'Escape') setEditing(null)
        }}
        onBlur={rename}
      />
    ) : (
      <button
        type="button"
        className="link name"
        title={t('school.rooms.rename')}
        disabled={busy}
        onClick={() => setEditing({ id: room.id, value: room.name })}
      >
        {room.name}
      </button>
    )

  return (
    <section className="panel" data-panel="rooms">
      <h3>{t('school.rooms.title')}</h3>
      <Hint short={t('school.rooms.hint')} more={t('school.rooms.hintMore')} />

      <form className="add-form" onSubmit={add}>
        <input
          value={name}
          maxLength={100}
          placeholder={t('school.rooms.newName')}
          aria-label={t('school.rooms.newName')}
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
        <label className="checkbox">
          <input
            type="checkbox"
            checked={shared}
            disabled={busy}
            onChange={(event) => setShared(event.target.checked)}
          />
          {t('school.rooms.shared')}
        </label>
        <button type="submit" disabled={busy || !name.trim()}>
          {t('common.add')}
        </button>
      </form>

      {rooms.length === 0 ? (
        <p className="hint">{t('school.rooms.empty')}</p>
      ) : (
        <ul className="class-list">
          {rooms.map((room) => (
            <li key={room.id} data-room={room.id} className={room.is_archived ? 'archived' : ''}>
              {title(room)}

              {/* делимость правится на месте: это свойство помещения, и
                  ради него не стоит заводить окно */}
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={room.is_shared}
                  disabled={busy}
                  onChange={(event) =>
                    onUpdate(room.id, { is_shared: event.target.checked })
                  }
                />
                {t('school.rooms.shared')}
              </label>

              <span className="hint">
                {t('school.rooms.usedBy', { count: room.slots })}
              </span>

              {/* архив вместо удаления там, где кабинет уже видел уроки:
                  кнопка не отказывает, а делает то, что человек и хотел */}
              <button
                type="button"
                className="link"
                disabled={busy}
                onClick={() => onUpdate(room.id, { is_archived: !room.is_archived })}
              >
                {room.is_archived
                  ? t('school.rooms.restore')
                  : t('school.rooms.archive')}
              </button>

              <button
                type="button"
                className="link"
                aria-label={t('school.reference.delete', { name: room.name })}
                disabled={busy}
                onClick={() => onDelete(room.id)}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
