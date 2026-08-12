import { Component } from 'react'

/**
 * Ловушка ошибок отрисовки.
 *
 * Без неё исключение в одной функции размонтирует всё дерево: страница
 * белеет, и даже кнопки, которые работали, исчезают. Бар остаётся снаружи
 * ловушки, поэтому уйти в другой раздел можно всегда.
 */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // в консоль — стек, пользователю ниже показываем текст
    console.error('Ошибка отрисовки страницы:', error, info)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <main className="page narrow">
        <h1>Страница не отрисовалась</h1>
        <p className="error">{error.message}</p>
        <p className="hint">
          Это ошибка в приложении, а не в ваших данных — они не пострадали.
          Попробуйте открыть раздел заново; если повторится, покажите это
          сообщение разработчику.
        </p>
        <button type="button" onClick={() => this.setState({ error: null })}>
          Попробовать снова
        </button>
      </main>
    )
  }
}
