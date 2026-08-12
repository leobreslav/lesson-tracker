import { Component } from 'react'
import { withTranslation } from 'react-i18next'

/**
 * A trap for render errors.
 *
 * Without it an exception in a single function unmounts the whole tree: the
 * page goes white and even the buttons that worked disappear. The bar stays
 * outside the trap, so another section is always reachable.
 *
 * A class component cannot call hooks, so the translator arrives as a prop
 * through withTranslation.
 */
class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // the stack goes to the console, the person below sees the text
    console.error(this.props.t('boundary.consoleError'), error, info)
  }

  render() {
    const { error } = this.state
    const { t } = this.props
    if (!error) return this.props.children

    return (
      <main className="page narrow">
        <h1>{t('boundary.title')}</h1>
        <p className="error">{error.message}</p>
        <p className="hint">{t('boundary.hint')}</p>
        <button type="button" onClick={() => this.setState({ error: null })}>
          {t('common.retry')}
        </button>
      </main>
    )
  }
}

export default withTranslation()(ErrorBoundary)
