import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'

/**
 * Классы школы: 6А, 6Б, DP1 — и кто их ведёт.
 *
 * Класс — это множество учеников с именем, и больше ничего. Курсов у него
 * нет и не будет: класс курса выводится из того, кто в этом курсе учится, и
 * записанная связь была бы вторым ответом на тот же вопрос. «Курс 6А», в
 * котором семеро из 6А и трое из 6Б, — обычное дело, а в поле стояло бы
 * «6А»; в школе с выбором предметов такого поля не существует вовсе.
 *
 * Поэтому здесь только имя, параллель и классный руководитель, а состав
 * набирается там, где живут сами ученики («Школа → Ученики»): класс — это
 * свойство человека, а не список, который кто-то ведёт отдельно.
 *
 * Классный руководитель ничего не открывает и не закрывает: это ответ на
 * вопрос «чей это класс», который задают, когда нужно кому-то написать.
 */
export default function HomegroupsPanel({
  homegroups,
  grades,
  teachers,
  year,
  busy,
  onCreate,
  onUpdate,
  onDelete,
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState({ name: '', grade: '', tutor: '' })
  const [editing, setEditing] = useState(null) // {id, value}

  const add = (event) => {
    event.preventDefault()
    const name = draft.name.trim()
    if (!name || busy || !year) return

    onCreate({
      year: year.id,
      name,
      grade: draft.grade ? Number(draft.grade) : null,
      tutor: draft.tutor ? Number(draft.tutor) : null,
    }).then(() => setDraft({ name: '', grade: '', tutor: '' }))
  }

  /* Переименование — кликом по названию: тот же способ, что у предмета,
     параллели и кабинета на этой же странице. */
  const rename = () => {
    if (!editing) return
    const value = editing.value.trim()
    const group = homegroups.find((one) => one.id === editing.id)
    setEditing(null)
    if (value && group && value !== group.name) onUpdate(editing.id, { name: value })
  }

  const title = (group) =>
    editing?.id === group.id ? (
      <input
        autoFocus
        value={editing.value}
        maxLength={100}
        aria-label={t('school.homegroups.rename')}
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
        title={t('school.homegroups.rename')}
        disabled={busy}
        onClick={() => setEditing({ id: group.id, value: group.name })}
      >
        {group.name}
      </button>
    )

  return (
    <section className="panel" data-panel="homegroups">
      <h3>{t('school.homegroups.title')}</h3>
      <Hint short={t('school.homegroups.hint')} more={t('school.homegroups.hintMore')} />

      {!year ? (
        <p className="hint">{t('school.homegroups.needYear')}</p>
      ) : (
        <>
          <form className="add-form" onSubmit={add}>
            <input
              value={draft.name}
              maxLength={100}
              placeholder={t('school.homegroups.newName')}
              aria-label={t('school.homegroups.newName')}
              disabled={busy}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />

            <label className="checkbox">
              {t('school.homegroups.grade')}
              <select
                value={draft.grade}
                disabled={busy}
                onChange={(event) => setDraft({ ...draft, grade: event.target.value })}
              >
                <option value="">{t('school.homegroups.noGrade')}</option>
                {grades.map((grade) => (
                  <option key={grade.id} value={grade.id}>
                    {grade.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="checkbox">
              {t('school.homegroups.tutor')}
              <select
                value={draft.tutor}
                disabled={busy}
                onChange={(event) => setDraft({ ...draft, tutor: event.target.value })}
              >
                <option value="">{t('school.homegroups.noTutor')}</option>
                {teachers.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </select>
            </label>

            <button type="submit" disabled={busy || !draft.name.trim()}>
              {t('common.add')}
            </button>
          </form>

          {homegroups.length === 0 ? (
            <p className="hint">{t('school.homegroups.empty')}</p>
          ) : (
            <ul className="class-list">
              {homegroups.map((group) => (
                <li key={group.id} data-homegroup={group.id}>
                  {title(group)}

                  {group.grade_name && <span className="hint">{group.grade_name}</span>}

                  {/* классного руководителя правят здесь же: это одно поле,
                      и окно ради него было бы дороже самой правки */}
                  <label className="checkbox">
                    {t('school.homegroups.tutor')}
                    <select
                      value={group.tutor ?? ''}
                      disabled={busy}
                      onChange={(event) =>
                        onUpdate(group.id, {
                          tutor: event.target.value ? Number(event.target.value) : null,
                        })
                      }
                    >
                      <option value="">{t('school.homegroups.noTutor')}</option>
                      {teachers.map((person) => (
                        <option key={person.id} value={person.id}>
                          {person.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <span className="hint">
                    {t('school.homegroups.inside', { count: group.students })}
                  </span>

                  <button
                    type="button"
                    className="link"
                    aria-label={t('school.reference.delete', { name: group.name })}
                    disabled={busy}
                    onClick={() => onDelete(group.id)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
