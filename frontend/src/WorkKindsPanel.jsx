import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  addTypicalKinds,
  createWorkKind,
  deleteWorkKind,
  fetchWorkKinds,
  saveWorkKind,
} from './api'

/**
 * Справочник видов работ школы: контрольная, проверочная, проект.
 *
 * Устроен как справочник систем оценивания, и это не совпадение, а решение:
 * вопрос у них один — «из чего учителю выбирать», — и второй механизм для
 * него разошёлся бы с первым в первой же правке. Читают все учителя, правит
 * администратор, рычаг у него один и честный: **какие виды разрешены**.
 *
 * Новая школа не получает ничего: угаданный список хуже пустого — школе, у
 * которой «зачёт» вместо контрольных, пришлось бы удалять то, чего она не
 * просила. Вместо посева кнопка «типовые», и нажать её дважды не страшно.
 *
 * Цвет — из палитры, а не свободный: столбцов в журнале до семидесяти, значок
 * односимвольный, и произвольный цвет даёт нечитаемые метки — белым по
 * светло-жёлтому.
 */

const COLORS = ['slate', 'blue', 'green', 'amber', 'violet', 'red']

export default function WorkKindsPanel() {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')

  const load = () =>
    fetchWorkKinds()
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

  if (data === null) {
    return (
      <section className="panel" data-panel="work-kinds">
        <h3>{t('workKinds.catalogue')}</h3>
        <p className="hint">{error ? error : t('common.loading')}</p>
      </section>
    )
  }

  return (
    <section className="panel" data-panel="work-kinds">
      <h3>{t('workKinds.catalogue')}</h3>
      <p className="hint">{t('workKinds.catalogueHint')}</p>
      {error && <p className="error">{error}</p>}

      {data.kinds.length === 0 ? (
        <p className="hint">{t('workKinds.none')}</p>
      ) : (
        <ul className="grading-list">
          {data.kinds.map((kind) => (
            <li key={kind.id} className={kind.is_allowed ? '' : 'off'}>
              <span className={`work-tag kind-${kind.color}`}>{kind.label}</span>
              <span className="name">{kind.name}</span>
              {kind.counts_to_term && (
                <span className="hint">{t('workKinds.counts')}</span>
              )}
              {!kind.is_allowed && (
                <span className="badge">{t('workKinds.forbidden')}</span>
              )}

              {data.may_edit && (
                <>
                  {/* цвет меняется на месте: их шесть, и выбирают из них
                      глазами — по тому, как значок будет выглядеть в шапке */}
                  <select
                    className="course-filter"
                    aria-label={t('workKinds.color')}
                    value={kind.color}
                    disabled={busy}
                    onChange={(event) =>
                      run(() => saveWorkKind(kind.id, { color: event.target.value }))
                    }
                  >
                    {COLORS.map((color) => (
                      <option key={color} value={color}>
                        {t(`workKinds.colors.${color}`)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="link"
                    disabled={busy}
                    onClick={() =>
                      run(() =>
                        saveWorkKind(kind.id, {
                          counts_to_term: !kind.counts_to_term,
                        }),
                      )
                    }
                  >
                    {t(kind.counts_to_term ? 'workKinds.dontCount' : 'workKinds.count')}
                  </button>
                  <button
                    type="button"
                    className="link"
                    disabled={busy}
                    onClick={() =>
                      run(() =>
                        saveWorkKind(kind.id, { is_allowed: !kind.is_allowed }),
                      )
                    }
                  >
                    {t(kind.is_allowed ? 'workKinds.forbid' : 'workKinds.allow')}
                  </button>
                  <button
                    type="button"
                    className="link"
                    aria-label={t('workKinds.delete', { name: kind.name })}
                    disabled={busy}
                    onClick={() => run(() => deleteWorkKind(kind.id))}
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
        <>
          <div className="row">
            <label className="field">
              <span>{t('workKinds.newName')}</span>
              <input
                value={name}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            {/* метка обязательна: ею вид подписан в журнале, и вывести её из
                имени нельзя — «Проект» и «Проверочная» дали бы одну букву */}
            <label className="field">
              <span>{t('workKinds.newLabel')}</span>
              <input
                value={label}
                maxLength={4}
                disabled={busy}
                onChange={(event) => setLabel(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={busy || !name.trim() || !label.trim()}
              onClick={() =>
                run(async () => {
                  await createWorkKind({ name: name.trim(), label: label.trim() })
                  setName('')
                  setLabel('')
                })
              }
            >
              {t('common.add')}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => run(addTypicalKinds)}
            >
              {t('workKinds.typical')}
            </button>
          </div>
          <p className="hint">{t('workKinds.typicalHint')}</p>
        </>
      )}
    </section>
  )
}
