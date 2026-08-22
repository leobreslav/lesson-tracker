import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Switch from './Switch'

/**
 * Какие курсы участвуют в массовой операции.
 *
 * Список чекбоксов это был — по одному на курс, — и на четырёх курсах
 * читался прекрасно. В школьном расписании их девятнадцать, и «скопировать
 * неделю всем, кроме одного» превращалось в восемнадцать нажатий: выбор
 * стоил дороже самой операции.
 *
 * Поэтому здесь три вещи, и каждая закрывает свой случай:
 *
 * - **«Все» и «никого»** — крайности, с которых начинают. Копируют обычно
 *   всё, а сузить проще, сняв лишнее с полного набора, чем набрать нужное с
 *   пустого;
 * - **группы** — то, чем эти курсы называют в разговоре: «все курсы
 *   Ивановой», «вся девятая параллель». Одна галочка вместо пяти;
 * - **счётчик** — сколько выбрано из скольких. Без него набор из
 *   девятнадцати чекбоксов не сосчитать глазами, а именно это число и
 *   решает, что произойдёт.
 *
 * Ось группировки выбирается тумблером, а не задана намертво: у
 * администратора вопрос звучит «чью неделю копируем», у учителя все курсы
 * свои — и осмысленна там только параллель. Поэтому умолчание считается по
 * самим данным: несколько учителей — группируем по ним, иначе по параллели.
 */
export default function ClassPicker({ classes, picked, onChange }) {
  const { t } = useTranslation()

  const teachers = useMemo(
    () => new Set(classes.flatMap((item) => (item.teachers ?? []).map((p) => p.id))),
    [classes],
  )
  const [byTeacher, setByTeacher] = useState(null)
  /* умолчание считается, а не хранится: список курсов приезжает после
     первого кадра, и состояние, взятое из пустого списка, застряло бы */
  const grouping = byTeacher ?? teachers.size > 1

  const groups = useMemo(() => {
    const found = new Map()
    for (const item of classes) {
      const key = grouping
        ? ((item.teachers ?? [])[0]?.name ?? t('classPicker.noTeacher'))
        : (item.grade_name ?? t('classPicker.noGrade'))
      if (!found.has(key)) found.set(key, [])
      found.get(key).push(item)
    }

    return [...found.entries()]
      .map(([title, items]) => ({ title, items }))
      .sort((one, two) => one.title.localeCompare(two.title))
  }, [classes, grouping, t])

  const replace = (next) => onChange(new Set(next))

  const toggle = (id) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }

  /* Группа переключается целиком, и в ту сторону, которой ей не хватает:
     отмечена не вся — дожимаем до полной, отмечена вся — снимаем. Так одна
     галочка отвечает и за «добавить этих», и за «убрать этих». */
  const toggleGroup = (items) => {
    const ids = items.map((item) => item.id)
    const next = new Set(picked)
    if (ids.every((id) => next.has(id))) ids.forEach((id) => next.delete(id))
    else ids.forEach((id) => next.add(id))
    onChange(next)
  }

  /* «Часть выбрана» — состояние DOM, а не атрибут: у React для него ничего
     нет, и ставится оно ссылкой на сам элемент */
  const partial = (some) => (node) => {
    if (node) node.indeterminate = some
  }

  return (
    <div className="class-picker">
      <div className="row middle class-picker-head">
        <span className="hint">{t('classPicker.label')}</span>

        <button
          type="button"
          className="link"
          disabled={picked.size === classes.length}
          onClick={() => replace(classes.map((item) => item.id))}
        >
          {t('classPicker.all')}
        </button>
        <button
          type="button"
          className="link"
          disabled={picked.size === 0}
          onClick={() => replace([])}
        >
          {t('classPicker.none')}
        </button>

        <span className="hint">
          {t('classPicker.chosen', { count: picked.size, total: classes.length })}
        </span>

        {/* тумблер незачем, пока группа одна: выбор из одного — не выбор */}
        {teachers.size > 1 && (
          <Switch
            label={t('classPicker.groupBy')}
            value={grouping}
            onChange={setByTeacher}
            options={[
              { value: true, label: t('classPicker.byTeacher') },
              { value: false, label: t('classPicker.byGrade') },
            ]}
          />
        )}
      </div>

      {groups.map((group) => {
        const inside = group.items.filter((item) => picked.has(item.id)).length

        return (
          <div className="class-group" key={group.title}>
            <label className="checkbox group">
              <input
                type="checkbox"
                checked={inside === group.items.length}
                ref={partial(inside > 0 && inside < group.items.length)}
                onChange={() => toggleGroup(group.items)}
              />
              {group.title}
              <span className="hint">
                {inside}/{group.items.length}
              </span>
            </label>

            <div className="class-items">
              {group.items.map((item) => (
                <label key={item.id} className="checkbox">
                  <input
                    type="checkbox"
                    checked={picked.has(item.id)}
                    onChange={() => toggle(item.id)}
                  />
                  {item.name}
                </label>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
