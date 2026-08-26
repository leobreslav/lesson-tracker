/**
 * Ширина подколонок журнала: сколько места отвести каждой работе дня.
 *
 * Дата в журнале делится на подколонки — сколько у занятия работ, столько и
 * колонок, плюс одна на присутствие. Чтобы отметка стояла ровно под своей
 * работой, ширину надо знать **обоим**: и значку в шапке, и клетке под ним.
 * Считается она здесь, одним числом на колонку, и раздаётся им обоим.
 *
 * Мерить надо по всему столбцу, а не по клетке: столбец должен сойтись сверху
 * донизу, поэтому берётся самая широкая отметка среди всех учеников. Отметка
 * бывает словом — «зачёт» рядом с «7» и «B», — и растянуть все колонки до
 * самой длинной значило бы раздуть журнал ради одной из семидесяти.
 *
 * **Единица — `rem`, и это главное правило этого модуля.** Сначала ширина
 * считалась в `ch`, то есть в ширине нуля **того шрифта, которым набран сам
 * элемент**. У значка работы кегль 0.75rem, у отметки — 0.9rem, и одна и та
 * же строка `calc(5ch + …)` давала в шапке одну ширину, а в клетке другую.
 * Пока отметки были односимвольными, обе упирались в нижнюю границу и
 * сходились — поэтому первая подколонка выглядела правильной, а всё правее
 * съезжало тем сильнее, чем длиннее слово. `rem` не зависит ни от шрифта, ни
 * от кегля элемента, и потому одинаков у обоих.
 */

/** Знак отметки при кегле таблицы, в rem. */
const GLYPH = 0.62

/** Воздух по краям подколонки, в rem. */
const AIR = 0.6

/**
 * Ширина одной подколонки по длине самой длинной отметки в ней.
 *
 * Нижней границы тут нет намеренно — её ставит `min-width` в стилях, общий у
 * шапки и клетки. Два источника одного числа разошлись бы молча.
 */
export function markWidth(longest) {
  return `${(Math.max(1, longest) * GLYPH + AIR).toFixed(2)}rem`
}

/**
 * Ширины всех подколонок журнала: по списку на столбец.
 *
 * `columns` и `students` — как их отдаёт сервер (`works.journal.build`).
 */
export function columnWidths(columns, students) {
  return columns.map((column, at) =>
    column.works.map((work) => {
      let longest = 1
      for (const row of students) {
        const mark = row.cells[at]?.marks.find((one) => one.work === work.id)
        if (mark) longest = Math.max(longest, String(mark.label).length)
      }
      return markWidth(longest)
    }),
  )
}

/*
 * --- ПРАВКА В КЛЕТКЕ ---------------------------------------------------------
 *
 * Журнал для учителя — не таблица на просмотр, а место, где ставят оценки.
 * Отсюда три вещи, которые считаются здесь, а не в компоненте: куда уходит
 * курсор, что стало с журналом после записи оценки и что — после отметки
 * присутствия.
 *
 * Вынесены они не ради чистоты. Ответ сервера надо положить обратно в тот же
 * журнал, которым нарисована таблица, и сделать это **не пересчитывая
 * отметку заново**: расчёт живёт на сервере (`services.final_grade`), и
 * второй такой же в браузере разошёлся бы с ним молча — то же правило, что у
 * сводки над таблицей и у раскладки плана.
 */

/**
 * Куда встать после записи: вниз (Enter) или вправо (Tab).
 *
 * Вниз — движение по умолчанию, и это не вкус: журнал заполняют **по
 * работе**, весь класс подряд, а не по ученику. Дойдя до низа, курсор
 * остаётся на месте: перескок в начало следующего столбца выглядит как
 * промах мимо клетки, а не как помощь.
 *
 * `place` — `{student, column, order}`; `order` это номер подколонки, либо
 * `ATTENDANCE` у крайней правой.
 */
export const ATTENDANCE = 'attendance'

export function nextPlace(place, where, { students, columns }) {
  if (where === 'down') {
    const row = students.findIndex((one) => one.id === place.student)
    const below = students[row + 1]
    return below ? { ...place, student: below.id } : place
  }

  const column = columns[place.column]
  const last = column ? column.works.length : 0

  // вправо: следующая работа того же дня, потом присутствие, потом первая
  // подколонка следующего дня. Дальше правого края не уходим
  if (place.order !== ATTENDANCE) {
    if (place.order + 1 < last) return { ...place, order: place.order + 1 }
    if (column && column.slot) return { ...place, order: ATTENDANCE }
  }

  const ahead = columns[place.column + 1]
  if (!ahead) return place
  return {
    student: place.student,
    column: place.column + 1,
    order: ahead.works.length ? 0 : ATTENDANCE,
  }
}

/**
 * Журнал с обновлённой отметкой — тем, что ответил сервер.
 *
 * `grade` — ответ `POST /api/works/<id>/grade/`: пересчитанный итог или
 * `null`, если отметку сняли. Ничего не считается заново, только кладётся на
 * место.
 */
export function applyGrade(journal, workId, studentId, grade) {
  // Порядок отметок внутри клетки значения не имеет: рисуется она по списку
  // работ столбца, а отметка к ним подбирается по номеру работы. Место
  // отметки в столбце держит раскладка, а не порядок в этом списке.
  const put = (cell) => {
    const had = cell.marks.some((one) => one.work === workId)
    if (!had && !grade) return cell

    const marks = cell.marks.filter((one) => one.work !== workId)
    if (grade) {
      marks.push({
        work: workId,
        label: grade.label,
        by_teacher: grade.by_teacher,
        earned: grade.earned,
        top: grade.top,
      })
    }
    return { ...cell, marks }
  }

  return {
    ...journal,
    students: journal.students.map((row) =>
      row.id === studentId ? { ...row, cells: row.cells.map(put) } : row,
    ),
  }
}

/** Журнал с обновлённой посещаемостью: `status` пустой значит «не отмечено». */
export function applyAttendance(journal, slotId, studentId, status) {
  const at = journal.columns.findIndex((one) => one.slot === slotId)
  if (at < 0) return journal

  return {
    ...journal,
    students: journal.students.map((row) =>
      row.id === studentId
        ? {
            ...row,
            cells: row.cells.map((cell, index) =>
              index === at
                ? { ...cell, attendance: status || null, note: status ? cell.note : '' }
                : cell,
            ),
          }
        : row,
    ),
  }
}
