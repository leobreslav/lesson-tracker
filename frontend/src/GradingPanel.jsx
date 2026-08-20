import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  addTypicalGrading,
  createGradingSystem,
  deleteGradingSystem,
  fetchGradingSystems,
  saveGradingSystem,
} from './api'

/**
 * Справочник систем оценивания школы.
 *
 * Читают его все учителя — им выбирать систему на своей работе, — а правит
 * администратор. Его рычаг тут один и честный: **какие системы разрешены**, и
 * какая рекомендована. Выбирать за учителя он не может, и это не забывчивость:
 * маленькая проверочная по пятибалльной рядом с контрольной по MYP — обычное
 * дело, и решает это тот, кто ведёт курс.
 *
 * Новая школа не получает ничего: угаданный набор хуже пустого списка — школе
 * с MYP пришлось бы удалять то, чего она не просила. Вместо этого кнопка
 * «типовые», и нажать её дважды не страшно.
 */
export default function GradingPanel() {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState('')

  const load = () =>
    fetchGradingSystems()
      .then(setData)
      .catch((problem) => setError(problem.message))

  useEffect(() => {
    load()
  }, [])

  const run = async (task) => {
    setBusy(true)
    setError(null)
    try {
      await task()
      await load()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return null

  return (
    <section className="panel" data-panel="grading">
      <h3>{t('grading.catalogue')}</h3>
      <p className="hint">{t('grading.catalogueHint')}</p>
      {error && <p className="error">{error}</p>}

      {data.systems.length === 0 ? (
        <p className="hint">{t('grading.none')}</p>
      ) : (
        <ul className="grading-list">
          {data.systems.map((system) => (
            <li key={system.id}>
              <span className="name">{system.name}</span>
              <span className="hint">{t(`grading.kind.${system.kind}`)}</span>
              <span className="hint bands">
                {system.bands.map((band) => `${band.label}≥${band.threshold}`).join(' · ')}
              </span>
              {data.default === system.id && (
                <span className="badge">{t('grading.recommended')}</span>
              )}
              {data.may_edit && (
                <>
                  <button
                    type="button"
                    className="link"
                    disabled={busy}
                    onClick={() =>
                      run(() =>
                        saveGradingSystem(system.id, { is_allowed: !system.is_allowed }),
                      )
                    }
                  >
                    {t(system.is_allowed ? 'grading.forbid' : 'grading.allow')}
                  </button>
                  <button
                    type="button"
                    className="link"
                    disabled={busy || data.default === system.id}
                    onClick={() => run(() => saveGradingSystem(system.id, { as_default: true }))}
                  >
                    {t('grading.recommend')}
                  </button>
                  <button
                    type="button"
                    className="link"
                    aria-label={t('grading.delete', { name: system.name })}
                    disabled={busy}
                    onClick={() => run(() => deleteGradingSystem(system.id))}
                  >
                    ✕
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {data.may_edit && (
        <div className="row">
          <label className="field">
            <span>{t('grading.newName')}</span>
            <input
              value={adding}
              disabled={busy}
              onChange={(event) => setAdding(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={busy || !adding.trim()}
            onClick={() =>
              run(async () => {
                await createGradingSystem({ name: adding.trim() })
                setAdding('')
              })
            }
          >
            {t('common.add')}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => run(addTypicalGrading)}
          >
            {t('grading.addTypical')}
          </button>
        </div>
      )}
    </section>
  )
}
