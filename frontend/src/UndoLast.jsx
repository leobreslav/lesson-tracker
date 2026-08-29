import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fetchSlotHistory, undoSlots } from './api'

/**
 * «Отменить последнее» для расписания — одна кнопка на обе сетки.
 *
 * Сеток две (`Agenda.jsx` и `SchoolSchedule.jsx`), а кнопка у них одна и та
 * же: две копии разошлись бы в первую же правку — сперва подписью, потом
 * тем, что считается последним шагом.
 *
 * **Курс кнопка не называет, и это не упрощение.** В учебном плане курс
 * выбран всегда, а тут за пять минут правят три курса подряд; «отменить
 * последнее» на этом экране значит последнее вообще, и находит его сервер —
 * по самому свежему снимку среди тех курсов, куда человеку можно писать.
 *
 * **Кнопка называет действие** («Отменить: перенос занятия»), а подсказка
 * добавляет подробность и автора. Безымянная отмена страшнее, чем полезна:
 * по ней не поймёшь, вернёшь ты удалённый час или чужую правку получасовой
 * давности.
 *
 * `watch` — то, что меняется вместе с расписанием: по нему список шагов и
 * перечитывается. Своего наблюдения за правками у кнопки нет намеренно —
 * она не знает, какие действия бывают, и знать не должна.
 */
export default function UndoLast({ watch, busy = false, onDone, onError }) {
  const { t } = useTranslation()
  const [step, setStep] = useState(null)
  const [working, setWorking] = useState(false)

  const reload = useCallback(() => {
    fetchSlotHistory()
      .then((payload) => setStep(payload.steps[0] ?? null))
      // молча: у отмены нет своего места на экране, и сообщение о том, что
      // не приехал список шагов, объясняло бы человеку не его задачу
      .catch(() => setStep(null))
  }, [])

  useEffect(() => {
    reload()
  }, [reload, watch])

  if (!step) return null

  const name = t(`agenda.undo.action.${step.action}`, { defaultValue: step.action })

  const click = () => {
    setWorking(true)
    undoSlots()
      .then(() => {
        // сперва обновляем расписание, потом себя: список шагов после
        // отмены другой — в нём появился сам откат
        onDone?.()
        reload()
      })
      .catch((err) => onError?.(err))
      .finally(() => setWorking(false))
  }

  return (
    <button
      type="button"
      className="secondary"
      disabled={busy || working}
      title={
        step.detail
          ? t('agenda.undo.what', {
              action: name,
              detail: step.detail,
              who: step.mine ? t('agenda.undo.mine') : (step.who?.name ?? ''),
            })
          : undefined
      }
      onClick={click}
    >
      {t('agenda.undo.label', { action: name })}
    </button>
  )
}
