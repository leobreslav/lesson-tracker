import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import EmptyState from './EmptyState'
import Switch from './Switch'
import { dateTime } from './dates'
import { fetchFeedback, markFeedbackHandled, updateMe } from './api'

/**
 * Всё, что написали пользователи, — раздел суперпользователя.
 *
 * Накопитель, а не переписка. Отвечать отсюда нельзя, и это решение: ответ
 * означал бы вторую почту внутри школьного журнала — со своими
 * уведомлениями, непрочитанным и ожиданием ответа, которого один человек на
 * всех дать не может. Ответом будет починка.
 *
 * Поэтому и состояний у обращения два, а не четыре: ждёт разбора — унесено в
 * работу. «В работе» и «принято» пришлось бы кому-то различать, а различать
 * их здесь некому.
 *
 * Умолчание списка — **неразобранное**: за этой страницей приходят с
 * вопросом «что нового», а не «покажи всё за год». Разобранное достаётся
 * тумблером, и по нему видно, что оно никуда не делось.
 */
export default function Feedback({ user, onLoggedOut, onSaved }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  const [shown, setShown] = useState('waiting') // waiting | handled
  const [kind, setKind] = useState('') // '' | bug | idea
  const [forwarding, setForwarding] = useState(Boolean(user?.forward_feedback))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () =>
      fetchFeedback({
        handled: shown === 'handled' ? 'true' : 'false',
        ...(kind ? { kind } : {}),
      })
        .then(setRows)
        .catch(handleError),
    [shown, kind, handleError],
  )

  useEffect(() => {
    load()
  }, [load])

  const mark = async (id) => {
    setBusy(true)
    setError(null)
    try {
      await markFeedbackHandled(id)
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /**
   * Пересылка на почту — настройка человека, поэтому и живёт в профиле.
   *
   * Стоит она здесь, а не в профиле, по той же причине, по какой чекбокс
   * «темы уроков» стоит над расписанием: включают её тогда, когда думают об
   * обращениях, а не когда правят своё имя.
   */
  const toggleForwarding = async () => {
    const next = !forwarding
    setForwarding(next)
    try {
      const saved = await updateMe({ forward_feedback: next })
      if (onSaved) onSaved(saved)
    } catch (err) {
      setForwarding(!next)
      handleError(err)
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('feedback.pageTitle')}</h1>
      </header>

      <p className="hint">{t('feedback.pageHint')}</p>

      <div className="row middle">
        <Switch
          label={t('feedback.shown')}
          value={shown}
          onChange={setShown}
          options={[
            { value: 'waiting', label: t('feedback.waiting') },
            { value: 'handled', label: t('feedback.handled') },
          ]}
        />

        <label className="checkbox">
          {t('feedback.kind')}
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="">{t('feedback.anyKind')}</option>
            <option value="bug">{t('feedback.bug')}</option>
            <option value="idea">{t('feedback.idea')}</option>
          </select>
        </label>

        <label className="checkbox">
          <input type="checkbox" checked={forwarding} onChange={toggleForwarding} />
          {t('feedback.forward')}
        </label>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {rows === null && <p>{t('common.loading')}</p>}

      {rows !== null && rows.length === 0 && (
        <EmptyState title={t('feedback.emptyTitle')}>
          {t('feedback.emptyHint')}
        </EmptyState>
      )}

      {rows !== null && rows.length > 0 && (
        <ul className="feedback-list">
          {rows.map((row) => (
            <li key={row.id} className="panel">
              <div className="row middle">
                <span className={`feedback-kind ${row.kind}`}>
                  {t(`feedback.${row.kind}`)}
                </span>
                <strong>{row.author_name || row.author_email || t('feedback.gone')}</strong>
                <span className="hint">{row.school_name}</span>
                <span className="hint">{dateTime(row.created_at)}</span>
              </div>

              {/* текст как написали, с переносами: сообщения пишут абзацами,
                  и склеенные в строку они читаются вдвое дольше */}
              <p className="feedback-text">{row.text}</p>

              <div className="row">
                {row.page && <span className="hint">{row.page}</span>}
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => mark(row.id)}
                >
                  {t(row.handled_at ? 'feedback.unhandle' : 'feedback.markHandled')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
