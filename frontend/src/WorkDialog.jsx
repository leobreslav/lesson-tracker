import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { fetchWorkImpact } from './api'
import { fromLocalInput, toLocalInput } from './dates'

/**
 * Настройки работы: название, окно времени, попытки, показ отметки.
 *
 * Черновика здесь нет и быть не должно — работа скрыта от учеников, пока
 * окно не открылось, и это единственный ответ на вопрос «видно ли её».
 * Поэтому даты обязательны: их не отложить «на потом», они и есть решение.
 *
 * У открытой работы окно правки называет цену: «сейчас решают N человек,
 * дано M ответов». Не запрещает — запрет здесь дороже ошибки, опечатку в
 * условии находят посреди урока, — но и молчать нельзя: правка, сделанная
 * вслепую, ломает то, что люди пишут прямо сейчас.
 */
export default function WorkDialog({
  work,
  courseId,
  slot,
  homework = false,
  busy,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  // `slot` — занятие, с которого работу заводят. Ничего, кроме привязки, он
  // не подставляет: подставленный текст из плана здесь уже был и оказался не
  // нужен — домашнее задание и так написано в плане и видно на уроке
  // `homework` задаётся **разделом**, из которого нажали, а не галочкой в
  // форме: классификация — наше слово, а человек знает, что он сейчас
  // задаёт. Тот же довод, по которому «дополнительный урок» в своё время
  // оказался плохим вопросом
  const [form, setForm] = useState(() => ({
    ...initial(work),
    ...(slot ? { slot } : {}),
    ...(homework ? { is_homework: true } : {}),
  }))
  const [impact, setImpact] = useState(null)

  useEffect(() => {
    if (!work) return undefined

    let current = true
    fetchWorkImpact(work.id)
      .then((result) => current && setImpact(result))
      .catch(() => current && setImpact(null))

    return () => {
      current = false
    }
  }, [work])

  const change = (field) => (event) => {
    const value =
      event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((current) => ({ ...current, [field]: value }))
  }

  const submit = (event) => {
    event.preventDefault()
    if (busy || !ready(form)) return

    onSubmit({
      course: courseId,
      slot: form.slot ?? null,
      title: form.title.trim(),
      description: form.description,
      opens_at: fromLocalInput(form.opens_at),
      closes_at: fromLocalInput(form.closes_at),
      attempts: form.limited ? Number(form.attempts) : null,
      show_result: form.show_result,
      on_paper: form.on_paper,
      is_homework: form.is_homework ?? false,
    })
  }

  return (
    <Modal onClose={onClose} title={t(work ? 'works.edit' : 'works.add')}>
      <form onSubmit={submit}>

        {impact?.answers > 0 && (
          <p className="hint warning">
            {t('works.impact', {
              answers: impact.answers,
              students: impact.students,
            })}
          </p>
        )}

        <label className="field-with-hint">
          {t('works.workTitle')}
          <input
            autoFocus
            value={form.title}
            maxLength={200}
            onChange={change('title')}
          />
        </label>

        {/* текст работы: у домашнего задания это оно и есть, у контрольной
            обычно пусто. Подставляется из плана кнопкой «задать как
            домашнее» — рекомендованное оттуда, фактическое здесь */}
        <label className="field-with-hint">
          {t('works.description')}
          <textarea rows={3} value={form.description} onChange={change('description')} />
        </label>

        <div className="row">
          <label className="field-with-hint">
            {t('works.opensAt')}
            <input
              type="datetime-local"
              value={form.opens_at}
              onChange={change('opens_at')}
            />
          </label>
          <label className="field-with-hint">
            {t('works.closesAt')}
            <input
              type="datetime-local"
              value={form.closes_at}
              onChange={change('closes_at')}
            />
          </label>
        </div>
        <p className="hint">{t('works.windowHint')}</p>

        {/* бумажная работа не решается онлайн, и попытки для неё значат
            ровно ничего — поэтому строка с ними прячется целиком */}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.on_paper}
            onChange={change('on_paper')}
          />
          {t('paper.onPaperSetting')}
        </label>
        <p className="hint">{t('paper.onPaperHint')}</p>

        {!form.on_paper && (
        <div className="row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.limited}
              onChange={change('limited')}
            />
            {t('works.limited')}
          </label>
          {form.limited && (
            <input
              type="number"
              min={1}
              max={20}
              value={form.attempts}
              aria-label={t('works.attempts')}
              onChange={change('attempts')}
            />
          )}
        </div>
        )}
        {!form.on_paper && <p className="hint">{t('works.attemptsHint')}</p>}

        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.show_result}
            onChange={change('show_result')}
          />
          {t('works.showResult')}
        </label>

        <div className="actions">
          <button type="submit" disabled={busy || !ready(form)}>
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

/** Новая работа открывается завтра на неделю: правится, но решать не надо. */
function initial(work) {
  if (work) {
    return {
      title: work.title,
      opens_at: toLocalInput(work.opens_at),
      closes_at: toLocalInput(work.closes_at),
      limited: work.attempts !== null,
      attempts: work.attempts ?? 1,
      show_result: work.show_result,
      on_paper: work.on_paper,
      description: work.description ?? '',
      slot: work.slot ?? null,
      is_homework: work.is_homework ?? false,
    }
  }

  const day = 24 * 60 * 60 * 1000
  const now = Date.now()

  return {
    title: '',
    opens_at: toLocalInput(new Date(now + day).toISOString()),
    closes_at: toLocalInput(new Date(now + 8 * day).toISOString()),
    limited: true,
    attempts: 1,
    show_result: true,
    on_paper: false,
    description: '',
    slot: null,
  }
}

const ready = (form) =>
  Boolean(form.title.trim() && form.opens_at && form.closes_at)
