import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fetchSlotHistory, redoSlots, undoSlots } from './api'

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
 * **После отмены она переворачивается в «Вернуть».** Отмена в расписании
 * односкоростная — глубже одного шага тут не ходят, и это решение, а не
 * недоделка, — поэтому второе нажатие всегда возвращало отменённое. Так оно
 * работало и раньше, но называлось при этом отменой: кнопка бралась из
 * `steps[0]`, а после отката самым свежим шагом был сам откат, и надпись
 * выходила «Отменить: отмену». Человек не мог понять, куда попадёт, и
 * расписание качалось между двумя состояниями.
 *
 * Что она сделает и как называется, **говорит сервер** (`undo` и `redo` в
 * ответе истории). Считать это здесь значило бы завести зеркало серверного
 * правила — а расходятся такие зеркала молча.
 *
 * `watch` — то, что меняется вместе с расписанием: по нему список шагов и
 * перечитывается. Своего наблюдения за правками у кнопки нет намеренно —
 * она не знает, какие действия бывают, и знать не должна.
 */
export default function UndoLast({ watch, busy = false, onDone, onError }) {
  const { t } = useTranslation()
  // `{ back, step }`: куда пойдём и чем это назвать. Одно поле, а не два
  // состояния рядом, — движений здесь взаимоисключающих ровно два, и
  // «включены оба» было бы состоянием, которого не бывает
  const [move, setMove] = useState(null)
  const [working, setWorking] = useState(false)

  const reload = useCallback(() => {
    fetchSlotHistory()
      .then((payload) =>
        setMove(
          payload.undo
            ? { back: true, step: payload.undo }
            : payload.redo
              ? { back: false, step: payload.redo }
              : null,
        ),
      )
      // молча: у отмены нет своего места на экране, и сообщение о том, что
      // не приехал список шагов, объясняло бы человеку не его задачу
      .catch(() => setMove(null))
  }, [])

  useEffect(() => {
    reload()
  }, [reload, watch])

  if (!move) return null

  const { back, step } = move
  const name = t(`agenda.undo.action.${step.action}`, { defaultValue: step.action })

  const click = () => {
    setWorking(true)
    ;(back ? undoSlots() : redoSlots())
      .then(() => {
        // сперва обновляем расписание, потом себя: после отмены кнопка
        // становится другой — она предлагает вернуть сделанное
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
          ? back
            ? t('agenda.undo.what', {
                action: name,
                detail: step.detail,
                who: step.mine ? t('agenda.undo.mine') : (step.who?.name ?? ''),
              })
            : t('agenda.redo.what', { action: name, detail: step.detail })
          : undefined
      }
      onClick={click}
    >
      {t(back ? 'agenda.undo.label' : 'agenda.redo.label', { action: name })}
    </button>
  )
}
