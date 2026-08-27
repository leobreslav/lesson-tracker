import { useMemo } from 'react'
import {
  debtSlots,
  freeSlots,
  layoutTotals,
  passedSlots,
  recordedSlots,
  stitchLayout,
} from './planLayout'
import { planRows } from './planLogic'
import { today } from './calendarLogic'

/**
 * Раскладка плана: даты у строк, границы четвертей, сводка и хвост
 * незанятых часов — одним проходом.
 *
 * Жила в `Plan.jsx` и была там на месте, пока раскладку видел только автор.
 * Теперь ту же таблицу открывает коллега (`Supervision.jsx`), и считать её
 * ему **своим** проходом нельзя: раскладка — это правило, а не оформление.
 * Час, за которым записан урок, показывает именно его; отменённый час места
 * в году не занимает; свободные часы идут хвостом за последним уроком. Два
 * прохода разошлись бы молча и в самом неудобном месте — двое смотрят в
 * один план и видят разные даты.
 *
 * Пересчёт стоит один проход по плану, поэтому ни дебаунса, ни запроса тут
 * нет: добавили урок — строки ниже съехали в тот же миг, и конец четверти
 * пришёлся на другую строку.
 *
 * Хук отдельным файлом, а не в `planLayout.js`: тот модуль чистый и
 * читается зеркальными тестами вместе с сервером (`mirrors/layout.json`).
 * React ему там незачем.
 */
export function usePlanLayout(nodes, ribbon) {
  return useMemo(() => {
    // сшивка одна на всё: и строки таблицы, и сводка, и хвост свободных
    // слотов — это разные взгляды на один проход, а не три расчёта
    const stitched = stitchLayout(planRows(nodes ?? []), ribbon, today())

    return {
      byId: new Map(stitched.map((row) => [row.id, row])),
      totals: layoutTotals(stitched, ribbon),
      free: freeSlots(stitched, ribbon),
      // прошедшие часы без записи: их видно строкой в таблице, а не только
      // счётчиком — час стоит в окружении, с датой, темой и соседями
      debts: debtSlots(ribbon, today()),
      // записанные — рядом с долгами и той же лентой: одно без другого не
      // читается
      recorded: recordedSlots(ribbon),
      // прошедшие часы: пока их нет, год не начался и учёт показывать нечем
      passed: passedSlots(ribbon, today()),
    }
  }, [nodes, ribbon])
}
