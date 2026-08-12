/** Выбор классов чекбоксами: массовые операции идут сразу по нескольким. */
export default function ClassPicker({ classes, picked, onChange }) {
  const toggle = (id) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }

  const all = () => onChange(new Set(classes.map((item) => item.id)))

  return (
    <div className="class-picker">
      <span className="hint">Классы:</span>

      {classes.map((item) => (
        <label key={item.id} className="checkbox">
          <input
            type="checkbox"
            checked={picked.has(item.id)}
            onChange={() => toggle(item.id)}
          />
          {item.name}
        </label>
      ))}

      {picked.size < classes.length && (
        <button type="button" className="link" onClick={all}>
          выбрать все
        </button>
      )}
    </div>
  )
}
