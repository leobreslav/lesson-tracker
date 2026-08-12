import { useTranslation } from 'react-i18next'

/** Classes as checkboxes: bulk operations run over several of them at once. */
export default function ClassPicker({ classes, picked, onChange }) {
  const { t } = useTranslation()
  const toggle = (id) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }

  const all = () => onChange(new Set(classes.map((item) => item.id)))

  return (
    <div className="class-picker">
      <span className="hint">{t('classPicker.label')}</span>

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
          {t('classPicker.all')}
        </button>
      )}
    </div>
  )
}
