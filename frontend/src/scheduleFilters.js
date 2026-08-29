/**
 * Сужение расписания школы: год обучения → предмет → учитель → курс.
 *
 * Фильтров было два, и работали они **пересечением**: выбранный учитель и
 * выбранный курс просто складывались условием. Курсы при этом перечислялись
 * все, поэтому выбрать курс чужого учителя было нечем помешать — и сетка
 * оказывалась пустой. Пустая сетка не ошибка и не сообщение: она выглядит
 * ровно как неделя, в которую ничего не поставили.
 *
 * Здесь фильтры — одна цепочка, и держится она на двух правилах:
 *
 * * **вниз сужаем**: выбранный предмет оставляет в списке учителей только
 *   тех, кто его ведёт, а выбранный учитель — только его курсы;
 * * **вверх доназначаем**: выбор говорит о себе всё, что определяет
 *   однозначно. Курс знает и своего ведущего, и предмет — значит оба
 *   встают сами; учитель, ведущий один предмет, называет и его.
 *
 * Пустое сочетание при этом становится недостижимым: до курса чужого
 * учителя в списке просто нет дороги.
 *
 * Модуль чистый и лежит отдельно от экрана намеренно: правила выбора — это
 * логика, а логику здесь держат под тестами (`tests/scheduleFilters.test.js`).
 * Сборка Vite неопределённых имён не ловит, а фильтр ломается молча.
 */

/** «Любой»: пустая строка, потому что это `value` пустого пункта `select`. */
export const ANY = ''

/**
 * От широкого к узкому — порядок цепочки, и он же порядок разбора.
 *
 * Год обучения стоит **первым**, потому что он самый широкий: предмет ведут
 * в нескольких параллелях, а параллель держит все предметы сразу. Из этого
 * же следует, что список годов не сужается ничем — как раньше список
 * предметов: сузить первый уровень значит отобрать дорогу к другому году,
 * не сбросив сначала всё остальное.
 */
export const LEVELS = ['grade', 'subject', 'teacher', 'course']

const id = (value) => (value === null || value === undefined ? ANY : String(value))

const subjectOf = (course) => id(course?.subject)

const gradeOf = (course) => id(course?.grade)

const teachersOf = (course) => (course?.teachers ?? []).map((teacher) => id(teacher.id))

/**
 * Ведущий курса — когда он один.
 *
 * Ведущий у курса и бывает один (`one_teacher_per_course`), но курс без
 * ведущего бывает тоже, и различать эти два случая приходится: у первого
 * имя есть, и его можно подставить, у второго подставлять нечего.
 */
const soleTeacherOf = (course) => {
  const people = teachersOf(course)
  return people.length === 1 ? people[0] : ANY
}

export const emptyFilters = () => ({
  grade: ANY,
  subject: ANY,
  teacher: ANY,
  course: ANY,
})

/**
 * Чем выбор называет себя на каждом уровне — для доназначения вверх.
 *
 * Тернарником это было («предмет или единственный ведущий»), и с третьим
 * широким уровнем тернарник пришлось бы вложить в тернарник. Списком видно,
 * что правило одно на все уровни: у учителя оно только строже — берётся
 * **единственный** ведущий, потому что курс без ведущего называть нечем.
 */
const NAMED_BY = {
  grade: (course) => gradeOf(course),
  subject: (course) => subjectOf(course),
  teacher: (course) => soleTeacherOf(course),
}

/** Подходит ли курс под выбранное. Пустое значение не спрашивает ни о чём. */
export function courseMatches(course, filters = {}) {
  if (filters.grade && gradeOf(course) !== filters.grade) return false
  if (filters.subject && subjectOf(course) !== filters.subject) return false
  if (filters.teacher && !teachersOf(course).includes(filters.teacher)) return false
  if (filters.course && id(course.id) !== filters.course) return false
  return true
}

/**
 * Подходит ли занятие. Предмет спрашивается у курса, а не у самого часа.
 *
 * Слот знает свой курс и своего ведущего (`teacher` — вывод из назначения),
 * а предмета у него нет: предмет — свойство курса, и второго ответа на этот
 * вопрос заводить незачем.
 */
export function slotMatches(slot, courseById, filters = {}) {
  // и год, и предмет спрашиваются у курса: у самого часа их нет, и второго
  // ответа на этот вопрос заводить незачем
  if (filters.grade && gradeOf(courseById.get(slot.course)) !== filters.grade) {
    return false
  }
  if (filters.subject && subjectOf(courseById.get(slot.course)) !== filters.subject) {
    return false
  }
  if (filters.teacher && id(slot.teacher) !== filters.teacher) return false
  if (filters.course && id(slot.course) !== filters.course) return false
  return true
}

/**
 * Что предлагать в каждом из трёх списков.
 *
 * Список предметов не сужается ничем: он первый в цепочке, и сузить его
 * значило бы отобрать возможность перейти к другому предмету, не сбросив
 * сначала всё остальное.
 */
export function filterOptions(courses, members, filters = emptyFilters()) {
  const ofGrade = courses.filter((course) =>
    courseMatches(course, { grade: filters.grade }),
  )
  const ofSubject = ofGrade.filter((course) =>
    courseMatches(course, { subject: filters.subject }),
  )
  const ofTeacher = ofSubject.filter((course) =>
    courseMatches(course, { teacher: filters.teacher }),
  )

  const grades = new Map()
  courses.forEach((course) => {
    if (course.grade != null) {
      grades.set(gradeOf(course), {
        id: gradeOf(course),
        name: course.grade_name ?? '',
        // порядок — по году обучения, а не по названию: «MYP 4» это девятый
        // год, и по алфавиту он встал бы между четвёртым и пятым
        level: course.grade_level ?? 0,
      })
    }
  })

  const subjects = new Map()
  ofGrade.forEach((course) => {
    if (course.subject != null) {
      subjects.set(subjectOf(course), {
        id: subjectOf(course),
        name: course.subject_name ?? '',
      })
    }
  })

  const leading = new Set(ofSubject.flatMap(teachersOf))

  return {
    grades: [...grades.values()].sort((a, b) => a.level - b.level),
    subjects: [...subjects.values()].sort((a, b) => a.name.localeCompare(b.name)),
    // порядок людей — серверный (имя, фамилия, почта); свой здесь означал бы
    // два разных порядка одного списка на соседних экранах
    teachers: members.filter((member) => leading.has(id(member.id))),
    courses: ofTeacher,
  }
}

/**
 * Выбор на одном из уровней — и всё, что из него следует.
 *
 * Выбранный уровень главный: уступают ему остальные, а не он им. Иначе
 * «выбрал курс» означало бы «ничего не изменилось», если до того стоял
 * чужой учитель.
 */
export function pick(courses, filters, level, value) {
  const next = { ...filters, [level]: value }

  if (!value) {
    // «все» на широком уровне — это шаг назад, а не второе условие: с
    // выбранным курсом «все учителя» не показали бы ни одного лишнего часа,
    // и человек нажимал бы в пустоту
    LEVELS.slice(LEVELS.indexOf(level) + 1).forEach((lower) => {
      next[lower] = ANY
    })
    return next
  }

  // противоречащее выбору снимаем, начиная с самого узкого: курс держится
  // за учителя, и снимать надо его, а не наоборот
  ;[...LEVELS].reverse().forEach((other) => {
    if (other === level || !next[other]) return
    if (!courses.some((course) => courseMatches(course, next))) next[other] = ANY
  })

  const candidates = courses.filter((course) => courseMatches(course, next))
  LEVELS.slice(0, LEVELS.indexOf(level)).forEach((wider) => {
    if (next[wider]) return
    const named = new Set(candidates.map((course) => NAMED_BY[wider](course)))
    // единственное — значит определено; курс без ведущего даёт пустое имя,
    // и подставлять его нельзя: тогда бы фильтр учителя спрятал его же часы
    const [only] = named
    if (named.size === 1 && only) next[wider] = only
  })

  return next
}

/**
 * Сохранённый выбор против сегодняшних данных.
 *
 * Выбор переживает уход со страницы (`useKept`) и год, и переназначение
 * ведущего: курс могли удалить, учителя — снять с курса. Такое значение
 * `select` показать не может и молча показывает пустоту, а сетка при этом
 * пуста по-настоящему. Снимаем начиная с узкого — как и в `pick`.
 *
 * Пока курсы не приехали, не снимаем ничего: пустой список означает «ещё
 * не знаем», и принять его за «такого курса нет» значило бы терять фильтр
 * при каждой перерисовке до ответа сервера.
 */
export function reconcile(courses, filters) {
  if (!courses.length) return filters

  const next = { ...filters }
  ;[...LEVELS].reverse().forEach((level) => {
    if (next[level] && !courses.some((course) => courseMatches(course, next))) {
      next[level] = ANY
    }
  })

  return next
}
