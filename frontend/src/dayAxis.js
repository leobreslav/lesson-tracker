/**
 * Ось столбцов дневного расписания: по чему разложен день.
 *
 * Сетка дня отвечает на «что происходит сегодня», и вопрос этот у разных
 * людей разный. Завуч, раскладывающий часы, смотрит **по курсам**; тот, кто
 * ищет свободное помещение, — **по кабинетам**; тот, кто ищет, кем закрыть
 * окно, — **по учителям**. Данные одни и те же, меняется только то, на что
 * смотрят как на столбец.
 *
 * Поэтому здесь нет ни одной ветки «а если кабинет»: ось — это две функции,
 * `columns` (какие столбцы бывают) и `keysOf` (в какие столбцы попадает
 * час), и всё остальное одинаково.
 *
 * Три правила, общие для всех осей, и каждое стоило бы поломки:
 *
 * * **пустой столбец остаётся.** Кабинет без единого часа — это и есть
 *   ответ «свободен», ради которого на ось кабинетов смотрят; курс без
 *   часов — место, куда час ставят. Спрятать пустое значило бы спрятать
 *   половину ответа;
 * * **час попадает в несколько столбцов, если так вышло.** На оси курсов
 *   столбец ровно один, на оси классов их будет столько, из скольких
 *   классов собрался курс. Поэтому `keysOf` возвращает список, а клетка
 *   умеет стопку;
 * * **крайний столбец «не указан» появляется только когда есть кому в нём
 *   стоять.** Час без кабинета обязан быть видно — пропавший с экрана урок
 *   это худший вид ошибки, — но пустой столбец «без кабинета» в школе, где
 *   кабинеты проставлены везде, только занимал бы место.
 */

/** Ключ крайнего столбца: час, у которого этого свойства нет. */
export const NONE = 'none'

export const AXES = ['course', 'teacher', 'room', 'homegroup']

/** Кто ведёт этот час: замена, если она названа, иначе ведущий курса. */
export const teacherOf = (slot) => slot.taught_by ?? slot.teacher ?? null

/**
 * Столбцы, в которые попадает час. Список, а не значение, — см. докстринг.
 *
 * Ключи — строки: столбец «не указан» соседствует с числовыми id, и Map с
 * ключами двух видов читается хуже, чем один вид, приведённый к строке.
 */
export function keysOf(slot, axis) {
  if (axis === 'room') return [slot.room ? String(slot.room) : NONE]
  if (axis === 'teacher') {
    const teacher = teacherOf(slot)
    return [teacher ? String(teacher) : NONE]
  }
  if (axis === 'homegroup') {
    // класс курса не записан нигде: он выводится из учеников, и курс,
    // собранный из кусков четырёх классов, попадает в четыре столбца сам.
    // Курс, в который ещё никого не зачислили, уходит в крайний столбец —
    // прятать его нельзя, иначе часы пропадают с экрана
    const groups = slot.homegroups ?? []
    return groups.length ? groups.map(String) : [NONE]
  }
  return [String(slot.course)]
}

/**
 * Столбцы дня: что показать и в каком порядке.
 *
 * `slots` нужны не для того, чтобы отобрать столбцы (пустые остаются), а
 * ради двух вещей: крайнего столбца «не указан» и часов, чей владелец в
 * справочник уже не попадает — архивный кабинет, снятый с курсов учитель.
 * Такой столбец добавляется по факту стоящего в нём часа: иначе час исчез
 * бы с экрана, а исчезнувший урок не находят месяцами.
 */
export function columns(
  axis,
  { courses = [], teachers = [], rooms = [], homegroups = [], slots = [] },
) {
  const known = new Map()

  if (axis === 'course') {
    for (const course of courses) {
      known.set(String(course.id), {
        key: String(course.id),
        id: course.id,
        name: course.name,
        note: (course.teachers ?? []).map((one) => one.name).join(', '),
      })
    }
  }

  if (axis === 'teacher') {
    for (const person of teachers) {
      known.set(String(person.id), {
        key: String(person.id),
        id: person.id,
        name: person.name,
        note: person.note ?? '',
      })
    }
  }

  if (axis === 'room') {
    for (const room of rooms) {
      // архивный кабинет из выбора убран, и в столбцах ему тоже не место —
      // если только в нём не стоит час, поставленный до архивации
      if (room.is_archived) continue
      known.set(String(room.id), {
        key: String(room.id),
        id: room.id,
        name: room.name,
        // делимость — признак, а не текст: перевод здесь означал бы, что
        // чистый модуль знает про словарь, а сырое «shared» доехало бы до
        // экрана словом. Подписывает его тот, кто рисует
        shared: room.is_shared ?? false,
        note: '',
      })
    }
  }

  if (axis === 'homegroup') {
    for (const group of homegroups) {
      known.set(String(group.id), {
        key: String(group.id),
        id: group.id,
        name: group.name,
        note: group.tutor_name ?? '',
      })
    }
  }

  let orphans = false
  const extra = new Map()
  for (const slot of slots) {
    for (const key of keysOf(slot, axis)) {
      if (key === NONE) {
        orphans = true
      } else if (!known.has(key)) {
        // владелец часа выпал из справочника: архивный кабинет, снятый с
        // курсов учитель. Имя берём у самого часа — другого источника нет
        extra.set(key, {
          key,
          id: Number(key),
          name: nameFromSlot(slot, axis) || key,
          note: '',
          gone: true,
        })
      }
    }
  }

  const all = [...known.values(), ...extra.values()]
  if (orphans) all.push({ key: NONE, id: null, name: null, note: '', none: true })
  return all
}

const nameFromSlot = (slot, axis) => {
  if (axis === 'room') return slot.room_name
  if (axis === 'teacher') return slot.teacher_name
  // у класса имени в самом часе нет: час знает только id классов своих
  // учеников — по нему столбец и назовётся, пока справочник не подъедет
  if (axis === 'homegroup') return null
  return slot.course_name
}

/**
 * Часы дня, разложенные по столбцам и номерам: `ключ` → `номер` → часы.
 *
 * Раскладка считается один раз на показ, а не поиском по всему списку в
 * каждой из двух сотен клеток: на девятнадцати курсах и десяти номерах это
 * разница между одним проходом и двумя тысячами.
 */
export function layout(slots, axis) {
  const byColumn = new Map()

  for (const slot of slots) {
    for (const key of keysOf(slot, axis)) {
      const numbers = byColumn.get(key) ?? new Map()
      const cell = numbers.get(slot.lesson_number) ?? []
      cell.push(slot)
      numbers.set(slot.lesson_number, cell)
      byColumn.set(key, numbers)
    }
  }

  return byColumn
}

/**
 * Что подставить в форму заведения часа, когда нажали «+» в этом столбце.
 *
 * Столбец не заменяет вопрос «какой курс» — час принадлежит курсу, и без
 * него его не создать, — а **сужает** его: на оси кабинетов кабинет уже
 * известен, на оси учителей известно, из чьих курсов выбирать. Поэтому
 * возвращается не готовый час, а то, что форма про него уже знает.
 */
export function prefillFor(axis, column) {
  if (!column || column.none || column.gone) return {}
  if (axis === 'room') return { room: column.id }
  if (axis === 'teacher') return { teacher: column.id }
  // класс не свойство часа: подставить его некуда, он только сужает выбор
  // курсов до тех, где учатся его ученики
  if (axis === 'homegroup') return { homegroup: column.id }
  return { course: column.id }
}
