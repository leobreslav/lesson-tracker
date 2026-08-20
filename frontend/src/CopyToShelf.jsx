import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import Switch from './Switch'
import { copyIntoSource, fetchSources } from './api'

/**
 * «Взять к себе»: куда и в каком виде.
 *
 * Оба вопроса задаются, и ни один не подразумевается. Книга — потому что своя
 * у человека не одна, и молчаливое «в первую попавшуюся» означает искать потом
 * руками. Вид — потому что разница видна не сразу, а стоит дорого: ссылка
 * оставляет одну задачу на всех (правку автора видно у себя), своя копия
 * отвязывается навсегда.
 *
 * Умолчание — ссылка: чаще всего задачу берут как есть, а лишняя копия значит,
 * что исправленная опечатка до неё не дойдёт.
 */
export default function CopyToShelf({ problem, section, onClose, onDone }) {
  const { t } = useTranslation()
  const [shelves, setShelves] = useState(null)
  const [into, setInto] = useState('')
  const [mode, setMode] = useState('link')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchSources()
      .then((answer) => {
        const mine = answer.sources.filter((one) => one.may_edit)
        setShelves(mine)
        if (mine.length) setInto(String(mine[0].id))
      })
      .catch((problem) => setError(problem.message))
  }, [])

  const copy = async () => {
    setBusy(true)
    setError(null)
    try {
      await copyIntoSource({ problem, section, into: Number(into), mode })
      onDone()
    } catch (trouble) {
      setError(trouble.message)
      setBusy(false)
    }
  }

  return (
    <Modal title={t('bank.copy.title')} onClose={onClose}>
      {error && <p className="error">{error}</p>}

      {shelves && shelves.length === 0 ? (
        // Своей книги ещё нет: сказать об этом надо словами — пустой селект
        // читается как поломка.
        <p className="hint">{t('bank.copy.noShelf')}</p>
      ) : (
        <>
          <label className="field">
            <span>{t('bank.copy.into')}</span>
            <select value={into} onChange={(event) => setInto(event.target.value)}>
              {(shelves || []).map((one) => (
                <option key={one.id} value={one.id}>
                  {one.title}
                </option>
              ))}
            </select>
          </label>

          <Switch
            value={mode}
            label={t('bank.copy.mode')}
            options={[
              { value: 'link', label: t('bank.copy.link') },
              { value: 'fork', label: t('bank.copy.fork') },
            ]}
            onChange={setMode}
          />
          <p className="hint">{t(`bank.copy.${mode}Hint`)}</p>

          <div className="row">
            <button type="button" onClick={copy} disabled={busy || !into}>
              {t('bank.copy.do')}
            </button>
            <button type="button" className="link" onClick={onClose}>
              {t('common.cancel')}
            </button>
          </div>
        </>
      )}
    </Modal>
  )
}
