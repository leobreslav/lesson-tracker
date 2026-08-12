import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <main className="page narrow">
      <h1>Страница не найдена</h1>
      <p className="hint">
        Такого адреса в трекере нет — возможно, ссылка устарела.
      </p>
      <p>
        <Link to="/">На главную</Link>
      </p>
    </main>
  )
}
