import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import {
  deleteInvitation,
  enrolRoster,
  enrolStudent,
  fetchInvitations,
  fetchStudents,
  previewRoster,
  removeStudent,
} from './api'

const PROBLEM_LIMIT = 5

/**
 * Состав курса: кто в нём есть и вставка списка целиком.
 *
 * Окном, а не блоком на карточке курса: тридцать строк в развёрнутой строке
 * списка курсов сделали бы страницу нечитаемой, а заходят сюда редко — в
 * начале года и когда кто-то перевёлся.
 *
 * Три списка, и все три нужны сразу. Учатся — обычный состав. Сняты — они
 * продолжают видеть сделанное, и вернуть их надо уметь той же кнопкой.
 * Ждут первого входа — приглашение уже написано, и без этого списка
 * администратор написал бы его второй раз.
 *
 * Разбирает вставку **сервер**: правила у неё не проще разбора CSV, а
 * второй их копии в браузере хватило бы ровно до первой правки одной из
 * них. Поэтому предпросмотр — это запрос, который ничего не пишет.
 */
export default function RosterDialog({ course, onClose, onChanged }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  const [waiting, setWaiting] = useState([])
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const reload = useCallback(
    () =>
      Promise.all([
        fetchStudents(course.id),
        fetchInvitations({ kind: 'student', course: course.id }),
      ]).then(([enrolled, invited]) => {
        setRows(enrolled)
        setWaiting(invited.filter((item) => !item.accepted))
      }),
    [course.id],
  )

  useEffect(() => {
    reload().catch((err) => setError(err.message))
  }, [reload])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await reload()
      onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // предпросмотр ничего не пишет и ни от чего не отказывается: ошибки
  // приезжают списком в теле, и показываем мы их, а не код ответа
  const check = () =>
    run(() => previewRoster(course.id, text).then(setPreview))

  const submit = () =>
    run(() =>
      enrolRoster(course.id, text).then(() => {
        setText('')
        setPreview(null)
      }),
    )

  const active = rows?.filter((row) => row.active) ?? []
  const past = rows?.filter((row) => !row.active) ?? []
  const problems = preview?.errors ?? []
  const nothingToDo =
    preview && !preview.enrol && !preview.restore && !preview.invite

  return (
    <Modal onClose={onClose} className="roster-window" title={t('roster.title', { name: course.name })}>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {rows === null ? (
        <p>{t('common.loading')}</p>
      ) : (
        <>
          <section className="panel">
            <span className="hint">
              {t('roster.enrolled', { count: active.length })}
            </span>
            {active.length === 0 ? (
              <p className="hint">{t('roster.nobody')}</p>
            ) : (
              <ul className="roster enrolled">
                {active.map((row) => (
                  <li key={row.id}>
                    <span className="name">{row.student_name}</span>
                    <span className="hint">{row.student_email}</span>
                    <button
                      type="button"
                      className="link"
                      disabled={busy}
                      aria-label={t('roster.remove', { name: row.student_name })}
                      onClick={() => run(() => removeStudent(row.id))}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {waiting.length > 0 && (
            <section className="panel">
              <span className="hint">
                {t('roster.waiting', { count: waiting.length })}
              </span>
              <ul className="roster waiting">
                {waiting.map((row) => (
                  <li key={row.id}>
                    <span className="name">{row.name || row.email}</span>
                    <span className="hint">
                      {row.name ? row.email : ''}
                      {row.conflict && (
                        <span className="warning">
                          {' '}
                          {t(`roster.conflict.${row.conflict}`, {
                            defaultValue: t(`errors.${row.conflict}`, {
                              email: row.email,
                            }),
                          })}
                        </span>
                      )}
                    </span>
                    <button
                      type="button"
                      className="link"
                      disabled={busy}
                      aria-label={t('roster.withdraw', { email: row.email })}
                      onClick={() => run(() => deleteInvitation(row.id))}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {past.length > 0 && (
            <section className="panel">
              <span className="hint">{t('roster.past', { count: past.length })}</span>
              <ul className="roster past">
                {past.map((row) => (
                  <li key={row.id}>
                    <span className="name">{row.student_name}</span>
                    <span className="hint">{row.student_email}</span>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        run(() => enrolStudent(course.id, row.student))
                      }
                    >
                      {t('roster.restore')}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      <section className="panel roster-paste">
        <span className="hint">{t('roster.paste')}</span>
        <p className="hint">{t('roster.pasteHint')}</p>
        <textarea
          rows={6}
          value={text}
          disabled={busy}
          placeholder={t('roster.placeholder')}
          aria-label={t('roster.paste')}
          onChange={(event) => {
            setText(event.target.value)
            setPreview(null)
          }}
        />

        {problems.length > 0 && (
          <ul className="csv-warnings">
            <li className="error">{t('roster.refused')}</li>
            {problems.slice(0, PROBLEM_LIMIT).map((problem, index) => (
              <li key={`${problem.code}-${index}`} className="error">
                {t(`errors.${problem.code}`, {
                  ...problem.params,
                  defaultValue: problem.detail,
                })}
              </li>
            ))}
            {problems.length > PROBLEM_LIMIT && (
              <li className="hint">
                {t('csv.moreProblems', { count: problems.length - PROBLEM_LIMIT })}
              </li>
            )}
          </ul>
        )}

        {preview && (
          <p className="hint" data-roster-preview>
            {t('roster.willDo', {
              enrol: preview.enrol,
              restore: preview.restore,
              invite: preview.invite,
              already: preview.already,
            })}
            {preview.blocked > 0 && ` ${t('roster.blocked', { count: preview.blocked })}`}
            {preview.duplicates > 0 &&
              ` ${t('roster.duplicates', { count: preview.duplicates })}`}
          </p>
        )}

        {/* поимённо — иначе «занят один адрес» это загадка */}
        {preview?.blocked > 0 && (
          <ul className="csv-warnings">
            {preview.people
              .filter((person) => person.action === 'blocked')
              .map((person) => (
                <li key={person.email} className="error">
                  {/* адрес в фразе уже назван — второй раз его не повторяем */}
                  {t(`errors.${person.code}`, {
                    email: person.email,
                    defaultValue: person.detail,
                  })}
                </li>
              ))}
          </ul>
        )}

        <div className="row">
          <button
            type="button"
            className="secondary"
            disabled={busy || !text.trim()}
            onClick={check}
          >
            {t('roster.check')}
          </button>
          <button
            type="button"
            disabled={busy || !preview || problems.length > 0 || nothingToDo}
            onClick={submit}
          >
            {t('roster.enrol')}
          </button>
        </div>
      </section>
    </Modal>
  )
}
