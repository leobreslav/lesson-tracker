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
 *   «сегодня» перед первым непрошедшим уроком;
 * - `week` — скобка недели слева: номер, место строки в группе и то, на
 *   какой строке писать подпись.
 *
 * Порядок черт постоянный — терм, каникулы, сегодня, — от крупного к
 * мелкому: так они читаются как вложенные, а не как список пометок.
 * Неделя строкой не является вовсе: она рисуется скобкой в левой колонке
 * и вертикального места не занимает — на сорока уроках десять лишних строк
 * рвали поток сильнее, чем помогали.
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

    const key = slot?.term?.id ?? null
    if (slot && key !== term) {
      term = key
      if (slot.term) before.push({ kind: 'term', ...slot.term })
    }

    if (slot?.break_before) before.push({ kind: 'break', ...slot.break_before })

    // черта «сегодня» — перед первым уроком, который ещё не прошёл
    const past = Boolean(today && slot && slot.date < today)
    if (today && slot && !past && !todayDone) {
      todayDone = true
      before.push({ kind: 'today' })
    }

    return { ...row, slot, past, before, after: [] }
  })

  markWeeks(stitched)

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

/**
 * Неделя: у каждой строки — её номер и то, ей ли достаётся подпись.
 *
 * Неделя удобнее как единица планирования, чем отдельная дата, но строкой
 * она стоила бы по строке на каждые три урока. Поэтому — подпись в первой
 * строке недели и заливка каждой второй: вертикального места ноль.
 *
 * Заголовок темы недели не имеет (у него нет слота), но скобку рвать не
 * должен: он получает неделю следующего под ним урока — он ведь эти уроки
 * и вводит. Уроки без слота остаются без скобки: их нет в расписании.
 *
 * Считается вторым проходом: подпись стоит посередине группы, а середину
 * знаешь, только дойдя до её конца.
 */
function markWeeks(rows) {
  // тема принимает неделю следующего урока
  const numbers = rows.map((row) => (row.is_section ? null : (row.slot?.week ?? null)))
  rows.forEach((row, index) => {
    if (!row.is_section) return
    numbers[index] = numbers.slice(index + 1).find((value) => value != null) ?? null
  })

  let start = 0
  const close = (end) => {
    const number = numbers[start]
    if (number == null) return

    // подпись достаётся первой строке **с датой**: у главы левая колонка
    // всегда пуста, и номер недели смотрелся бы там случайным
    let labelled = -1
    for (let index = start; index <= end; index += 1) {
      if (rows[index].slot) {
        labelled = index
        break
      }
    }
    // неделя без единого урока — не неделя: ни подписи, ни заливки
    if (labelled === -1) return

    for (let index = start; index <= end; index += 1) {
      rows[index].week = {
        number,
        first: index === start,
        last: index === end,
        labelled: index === labelled,
      }
    }
  }

  for (let index = 1; index <= rows.length; index += 1) {
    if (index < rows.length && numbers[index] === numbers[start]) continue
    close(index - 1)
    start = index
  }
}

/**
 * Сводка сверху: сколько слотов, сколько уроков и чем это кончится.
 *
 * На вход идут **сшитые** строки — те же самые, что рисует таблица.
 * Пересчитывать по ленте заново нельзя: у двух независимых проходов было бы
 * два ответа на вопрос «поместился ли план», и таблица могла показать дату
 * у последнего урока, а сводка рядом написать «не помещается».
 */
export function layoutTotals(stitched, ribbon) {
  const lessons = stitched.filter((row) => !row.is_section)
  const placed = lessons.filter((row) => row.slot)

  return {
    slots: ribbon.length,
    lessons: lessons.length,
    balance: ribbon.length - lessons.length,
    // последний урок плана есть только тогда, когда план поместился целиком
    lastDate:
      placed.length === lessons.length && lessons.length
        ? lessons[lessons.length - 1].slot.date
        : null,
    missing: lessons.length - placed.length,
  }
}

/**
 * Слоты, на которые не пришлось ни одного урока плана.
 *
 * Сводка говорит «баланс +82», но где эти восемьдесят два дня — по числу не
 * видно. При позиционном сопоставлении они идут все подряд после последнего
 * урока плана, поэтому это просто хвост ленты.
 *
 * Подпись недели ставится там же, где и в плане: у первой строки недели, —
 * и первая свободная строка её не получает, если неделя началась ещё
 * уроками плана.
 *
 * На вход, как и у сводки, идут сшитые строки: сшивка на странице одна.
 */
export function freeSlots(stitched, ribbon) {
  // сколько слотов заняли уроки — оттуда и начинается хвост; считается по
  // той же сшивке, что и сводка, чтобы «свободных 59» и «баланс +59» не
  // расходились на единицу
  const taken = stitched.filter((row) => row.slot).length
  let previous = taken > 0 ? (ribbon[taken - 1]?.week ?? null) : null

  return ribbon.slice(taken).map((slot) => {
    const labelled = slot.week != null && slot.week !== previous
    previous = slot.week
    return { slot, labelled }
  })
}
