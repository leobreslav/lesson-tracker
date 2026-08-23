import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import Modal from './Modal'
import { fetchGradingSystems, fetchWorkImpact } from './api'
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
  const [systems, setSystems] = useState([])
  const [form, setForm] = useState(() => ({
    ...initial(work),
    ...(slot ? { slot } : {}),
    ...(homework ? { is_homework: true } : {}),
  }))
  const [impact, setImpact] = useState(null)

  /* Список систем школы: показываются только разрешённые — сервер их и не
     отдаёт другими, а форма не должна предлагать то, чего он не примет. */
  useEffect(() => {
    let alive = true
    fetchGradingSystems()
      .then((answer) => alive && setSystems(answer.systems.filter((one) => one.is_allowed)))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

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
      is_homework: form.is_homework ?? false,
      is_summative: form.is_summative ?? false,
      grading_system: form.grading_system ?? null,
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
            домашнее» — рекомендованное оттуда, фактическое здесь.

            Звалось поле «Что делать», и это читалось вопросом к учителю —
            «что мне сейчас делать в этой форме?», — а не заголовком того,
            что увидит ученик. «Пояснения к работе» вопросом не читается */}
        <label className="field-with-hint">
          {t('works.description')}
          <textarea rows={3} value={form.description} onChange={change('description')} />
        </label>
        <Hint
          short={t('works.descriptionHint')}
          more={t('works.descriptionHintMore')}
        />

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
        {/* Окно решает не «видно ли работу», а «принимаются ли решения», и
            это две разные вещи. Строка обещала первое — «ученик видит работу
            только пока окно открыто», — а на деле после закрытия у него
            остаётся всё: условия, свои ответы, баллы и переписка с учителем
            по задаче (треды окна не знают вовсе, право там по участию).
            Пропадает ровно одно — возможность прислать новое решение */}
        <Hint short={t('works.windowHint')} more={t('works.windowHintMore')} />

        {/* Система оценивания — решение учителя, на каждой работе своё:
            маленькая проверочная по пятибалльной рядом с контрольной по MYP
            это обычное дело. Администратор только ограничивает список. */}
        <label className="field">
          <span>{t('grading.system')}</span>
          <select
            value={form.grading_system ?? ''}
            onChange={(event) =>
              setForm({
                ...form,
                grading_system: event.target.value ? Number(event.target.value) : null,
              })
            }
          >
            <option value="">{t('grading.noSystem')}</option>
            {systems.map((system) => (
              <option key={system.id} value={system.id}>
                {system.name}
              </option>
            ))}
          </select>
        </label>
        {/* пояснение нужно самому первому пункту списка: «Только баллы, без
            отметки» — это отказ от системы, и по подписи не видно, что при
            этом остаётся. Внутрь `<option>` подсказку не положить, поэтому
            она стоит под селектом и говорит про оба случая сразу.

            Правила перевода у системы настоящие — полосы с порогами
            (`GradingSystem.bands`, считает `services.grade_for`), и в
            подробностях сказано, где их смотреть: задаёт их школа, а не эта
            форма, и искать их иначе негде */}
        <Hint short={t('grading.systemHint')} more={t('grading.systemHintMore')} />

        {/* формативную оценивают как придётся, и в итог она не идёт */}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.is_summative}
            onChange={change('is_summative')}
          />
          {t('works.summative')}
        </label>
        <p className="hint">{t('works.summativeHint')}</p>

        {/* попытки — про работу целиком, а не про отдельный вопрос: чекбокса
            «на бумаге» тут больше нет, и прятать эту строку стало не по чему.
            Работа, все ячейки которой пишут на бумаге, попыток не тратит, и
            число в них ничего не портит.

            Ряд по центру (`middle`), а не по низу: умолчание `flex-end`
            верно для ряда полей с подписями сверху, а здесь рядом стоят
            голый чекбокс ростом со строку и поле ростом с контрол — по
            нижнему краю подпись прибивало к донышку поля, и она читалась
            не как заголовок этого числа, а как что-то лежащее под ним */}
        <div className="row middle">
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
        {/* «Один: ученик отправляет…» читалось как начало фразы, а не как
            пример: число в поле и число в тексте связывались не сразу.
            Теперь оба случая названы одинаково — «Стоит 1 — …», «Стоит 3 — …» */}
        <Hint short={t('works.attemptsHint')} more={t('works.attemptsHintMore')} />

        {/* «отметка» — слово из школьного обихода, и в форме оно ничего не
            называет. Скрывает флажок не «верно/неверно», а **баллы**: балл за
            каждую задачу, итоговую отметку за работу и комментарий учителя —
            всё разом (`show_result` у модели, `services.mark_for`). Первая
            версия подсказки говорила про вердикт, и это осталось от времён,
            когда вердикт был галочкой; баллом он стал давно */}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.show_result}
            onChange={change('show_result')}
          />
          {t('works.showResult')}
        </label>
        <Hint
          short={t('works.showResultHint')}
          more={t('works.showResultHintMore')}
        />

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
      is_summative: work.is_summative ?? false,
      grading_system: work.grading_system ?? null,
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
    is_summative: false,
    grading_system: null,
    description: '',
    slot: null,
  }
}

const ready = (form) =>
  Boolean(form.title.trim() && form.opens_at && form.closes_at)
