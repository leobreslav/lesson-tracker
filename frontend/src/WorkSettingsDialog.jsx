import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import WorkSettings from './WorkSettings'
import { fromLocalInput, toLocalInput } from './dates'
import { updateWork } from './api'

/**
 * Окно настроек работы: то, что настраивают один раз и потом не трогают.
 *
 * Стояло это всё на виду, вперемешку с заданием, и заказчик попросил убрать:
 * главное в работе — текст, который прочтёт класс, и задачи, которые он
 * решит, а окно времени, попытки и три флажка занимали половину экрана над
 * ними. Окно тут право по той же причине, по какой оно право при заведении
 * работы: полей мало, заходят сюда редко и с одним вопросом.
 *
 * Сохраняет оно себя само и не ждёт «Сохранить» у задания: настройки и текст
 * — две разные правки, и общая кнопка означала бы, что смену срока нельзя
 * записать, не дописав задание.
 */
export default function WorkSettingsDialog({ work, onSaved, onClose }) {
  const { t } = useTranslation()

  const [form, setForm] = useState(() => ({
    opens_at: toLocalInput(work.opens_at),
    closes_at: toLocalInput(work.closes_at),
    limited: work.attempts !== null,
    attempts: work.attempts ?? 1,
    show_result: work.show_result,
    is_summative: work.is_summative ?? false,
    is_homework: work.is_homework ?? false,
    kind: work.kind ?? null,
    grading_system: work.grading_system ?? null,
    slot: work.slot ?? null,
  }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (event) => {
    event.preventDefault()
    if (busy || !form.opens_at || !form.closes_at) return

    setBusy(true)
    setError(null)
    try {
      const saved = await updateWork(work.id, {
        opens_at: fromLocalInput(form.opens_at),
        closes_at: fromLocalInput(form.closes_at),
        attempts: form.limited ? Number(form.attempts) : null,
        show_result: form.show_result,
        is_summative: form.is_summative,
        is_homework: form.is_homework,
        kind: form.kind ?? null,
        grading_system: form.grading_system ?? null,
        slot: form.slot ?? null,
      })
      onSaved(saved)
    } catch (failure) {
      setError(failure.message)
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} title={t('works.edit')}>
      <form onSubmit={submit}>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <WorkSettings
          form={form}
          setForm={setForm}
          courseId={work.course}
          busy={busy}
        />

        <div className="actions">
          <button
            type="submit"
            disabled={busy || !form.opens_at || !form.closes_at}
          >
            {t('common.save')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
