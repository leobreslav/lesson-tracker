import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import { deleteCourse, publishPlan } from './api'
import { today } from './calendarLogic'
import { longDate } from './dates'

/**
 * Удаление курса — с ценой и с выходом для плана.
 *
 * Нативным `confirm` это было, и он называл одно имя курса. А курс держат
 * три разные вещи, и каждая значит своё: строки плана, занятия расписания и
 * работы (`PROTECT` у всех трёх). Отказ приходил после нажатия, красной
 * строкой в углу страницы, и совет в нём — «сначала очистите курс» — вёл в
 * ловушку: очистить план значит удалить строки по одной, а следом удаление
 * курса уносит **журнал**, и вернуть их становится нечем.
 *
 * Поэтому порядок обратный, и он предлагается прямо здесь:
 *
 *   1. сохранить план в библиотеку — там он переживёт курс и следующей
 *      осенью возьмётся в новый;
 *   2. удалить курс вместе с планом (`?force=true`).
 *
 * **Занятия и работы флаг не уносит никогда**, и кнопки для этого тут нет.
 * Разница не в осторожности, а в существе: план — это текст, и копия его на
 * полке равноценна оригиналу; за работой стоят ответы учеников и оценки, за
 * занятием — запись о том, что урок был. Копии, равноценной им, не бывает.
 * Когда держат они, окно так и говорит и называет, у кого спросить.
 *
 * Спрашивается всё это **после** первой попытки, а не до: чисел («сколько в
 * курсе строк плана») в списке курсов нет, а заводить ради редкого действия
 * отдельный запрос дороже, чем показать то, что и так приезжает отказом.
 */
export default function CourseDeleteDialog({ course, onClose, onDone }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  //: параметры отказа `course_in_use` — они и есть цена
  const [held, setHeld] = useState(null)
  //: название шаблона, если план успели положить на полку
  const [saved, setSaved] = useState(null)
  const [understood, setUnderstood] = useState(false)
  /*
   * Под каким именем класть на полку — спрашивается, а не подставляется молча.
   *
   * Умолчание с датой то же, что у «сохранить копию» на самом плане: два
   * «9Б Алгебра» на полке не различить. Но имя тут важнее, чем там: курс
   * уходит, и найти эту запись потом можно будет только по названию — а
   * «9Б Алгебра — 30 августа» через год не говорит ни о предмете, ни о том,
   * чем этот план был хорош.
   */
  const [title, setTitle] = useState(`${course.name} — ${longDate(today())}`)

  const drop = (force = false) => {
    setBusy(true)
    setError(null)
    deleteCourse(course.id, force)
      .then(() => {
        onDone()
        onClose()
      })
      .catch((err) => {
        // отказ по занятости — не ошибка, а следующий шаг разговора:
        // окно показывает цену и то, что с ней можно сделать
        if (err.code === 'course_in_use') setHeld(err.params)
        else setError(err.message)
      })
      .finally(() => setBusy(false))
  }

  const toShelf = () => {
    setBusy(true)
    setError(null)
    publishPlan({
      course: course.id,
      title: title.trim(),
      description: '',
      // всей школе: курс уходит, и держать программу в черновике у автора
      // значит спрятать её от тех, кому она и пригодится
      is_published: true,
      // снимок, а не ведомый: курса, с которого его обновлять, сейчас не
      // станет, и пометка «веду» обещала бы то, чего больше нет
      is_live: false,
    })
      .then((template) => setSaved(template.title))
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false))
  }

  const planOnly = held?.plan_only
  // потерять можно только то, что ещё нигде не лежит: положили на полку —
  // и подтверждать нечего
  const needsConfirming = planOnly && !saved

  return (
    <Modal
      title={t('school.courses.remove.title', { name: course.name })}
      onClose={onClose}
    >
      {!held && <p className="hint">{t('school.courses.remove.ask')}</p>}

      {held && (
        <p className="hint">
          {t('school.courses.remove.held', {
            plan_rows: held.plan_rows,
            slots: held.slots,
            works: held.works,
          })}
        </p>
      )}

      {/* Занятия и работы этим окном не убрать — и не должны. Говорим, у
          кого спросить: курс принадлежит школе, а всё на нём — тому, кто
          его ведёт */}
      {held && !planOnly && (
        <p className="hint">
          {t('school.courses.remove.askTeacher', {
            who: (held.teachers ?? []).join(', ') || t('school.courses.remove.itsTeacher'),
          })}
        </p>
      )}

      {planOnly && !saved && (
        <>
          <p className="hint">{t('school.courses.remove.shelfOffer')}</p>
          {/* имя спрашивается, а не подставляется молча: курс уходит, и
              найти эту запись потом можно будет только по названию */}
          <label className="field-with-hint">
            <span>{t('school.courses.remove.shelfName')}</span>
            <input
              value={title}
              disabled={busy}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
        </>
      )}

      {saved && (
        <>
          <p className="hint" role="status">
            {t('school.courses.remove.saved', { title: saved })}
          </p>
          {/*
            Сказать это прямо пришлось потому, что кнопка рядом называется
            «Удалить вместе с планом», и стоя под строкой о библиотеке она
            читается как «удалит и копию». Удаляется план **курса**; копия на
            полке — отдельная запись, курса она не знает и его не переживает,
            а живёт сама по себе.
          */}
          <p className="hint">{t('school.courses.remove.copyStays')}</p>
        </>
      )}

      {/* Галочка стоит там же, где у сноса темы, и по той же причине: она
          про **потерю**, а не про подтверждение вообще. Положили план на
          полку — терять нечего, и лишний вопрос только приучает
          проматывать не глядя */}
      {needsConfirming && (
        <label className="checkbox danger">
          <input
            type="checkbox"
            checked={understood}
            onChange={(event) => setUnderstood(event.target.checked)}
          />
          {t('school.courses.remove.confirmLoss', { plan_rows: held.plan_rows })}
        </label>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="actions">
        {!held && (
          <button type="button" disabled={busy} onClick={() => drop()}>
            {t('common.delete')}
          </button>
        )}

        {planOnly && !saved && (
          <button type="button" disabled={busy || !title.trim()} onClick={toShelf}>
            {t('school.courses.remove.toShelf')}
          </button>
        )}

        {planOnly && (
          <button
            type="button"
            className="secondary"
            disabled={busy || (needsConfirming && !understood)}
            onClick={() => drop(true)}
          >
            {t('school.courses.remove.withPlan', { count: held.plan_rows })}
          </button>
        )}

        <button type="button" className="secondary" onClick={onClose}>
          {held && !planOnly ? t('common.close') : t('common.cancel')}
        </button>
      </div>
    </Modal>
  )
}
