/**
 * The empty state of a section: what it is for and what to do next.
 *
 * Instead of a bare "nothing here" — an explanation and one obvious action.
 * Buttons come in as props so every page decides for itself.
 */
export default function EmptyState({ title, children, actions }) {
  return (
    <section className="panel empty-state">
      {title && <h3>{title}</h3>}
      <p className="hint">{children}</p>
      {actions && <div className="actions wrap">{actions}</div>}
    </section>
  )
}
