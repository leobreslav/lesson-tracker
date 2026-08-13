/**
 * Сшивка плана с лентой слотов — то, что показывает даты прямо в таблице.
 *
 * Раскладка позиционная: i-й урок плана попадает в i-й неотменённый слот.
 * Из двух её половин от правки плана меняется ровно одна — порядок уроков, —
 * и она тривиальна, это zip. Календарь (какие дни учебные, где границы
 * термов, где каникулы) приходит с сервера лентой и от плана не зависит
 * вовсе, поэтому сшивать можно здесь: строки сдвигаются в тот же миг, когда
 * урок добавили, удалили или перетащили, и ни одного настоящего правила при
 * этом на клиент не переехало.
 *
 * Ничего не форматирует: наружу отдаются даты строками ISO и коды, а
 * человеческие подписи собирает страница через `dates.js` и словарь.
 */

/**
 * Строки отображения (темы и уроки по порядку) + лента → что показать.
 *
 * У каждой строки появляется:
 * - `slot` — слот, в который лёг урок, или null («не помещается»);
 * - `past` — урок уже прошёл;
 * - `range` — у темы: с какой по какую дату идут её уроки;
 * - `before` — то, что рисуется перед строкой: заголовок терма при его
 *   смене, каникулы перед уроком, который стоит уже после них, и черта
 *   «сегодня» перед первым непрошедшим уроком.
 */
export function stitchLayout(rows, ribbon, today = null) {
  let index = 0
  let term // терм предыдущего урока: по его смене рисуется заголовок
  let todayDone = false

  const stitched = rows.map((row) => {
    if (row.is_section) return { ...row, children: [], range: null }

    const slot = index < ribbon.length ? ribbon[index] : null
    index += 1

    const before = []
    if (slot?.break_before) before.push({ kind: 'break', ...slot.break_before })

    const key = slot?.term?.id ?? null
    if (slot && key !== term) {
      term = key
      if (slot.term) before.push({ kind: 'term', ...slot.term })
    }

    // черта «сегодня» — перед первым уроком, который ещё не прошёл
    const past = Boolean(today && slot && slot.date < today)
    if (today && slot && !past && !todayDone) {
      todayDone = true
      before.push({ kind: 'today' })
    }

    return { ...row, slot, past, before, after: [] }
  })

  // диапазон темы: от первого её урока до последнего поместившегося
  let section = null
  for (const row of stitched) {
    if (row.is_section) {
      section = row
      continue
    }
    if (!section || row.section_id !== section.id) continue

    section.range = section.range ?? { from: null, to: null, missing: 0 }
    if (row.slot) {
      section.range.from = section.range.from ?? row.slot.date
      section.range.to = row.slot.date
    } else {
      section.range.missing += 1
    }
  }

  return stitched
}

/** Сводка сверху: сколько слотов, сколько уроков и чем это кончится. */
export function layoutTotals(rows, ribbon) {
  const lessons = rows.filter((row) => !row.is_section).length
  const slots = ribbon.length

  return {
    slots,
    lessons,
    balance: slots - lessons,
    // последний урок плана есть только тогда, когда план поместился целиком
    lastDate: lessons > 0 && lessons <= slots ? ribbon[lessons - 1].date : null,
    missing: Math.max(0, lessons - slots),
  }
}
