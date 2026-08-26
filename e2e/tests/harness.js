import { expect, test as base } from '@playwright/test'

/**
 * What every test starts from: a clean database, a signed-in person, and a
 * microphone held up to the browser console.
 *
 * The console listener is the reason these tests exist. Twice now a page has
 * shipped with a ReferenceError that rendered a blank section while every
 * unit test stayed green — `vite build` does not evaluate the code, so only
 * a browser can catch it. Any console error or uncaught exception fails the
 * test that produced it, whatever else that test was checking.
 */

// Noise that is not the application's fault. Anything added here needs a
// reason next to it, or the listener quietly stops being a safety net.
const IGNORED = [
  // no favicon in the bundle; the browser asks anyway
  /favicon\.ico/,
  // Google Identity Services is not reachable from the test network, and the
  // sign-in page is only visited to check it renders
  /accounts\.google\.com|gsi\/client/,
]

/*
 * Ошибки, которых тест ждёт **сам**.
 *
 * Список выше глобальный и потому короткий: всё, что в нём, перестаёт быть
 * видимым во всех тестах сразу. А бывает ошибка ожидаемая ровно в одном
 * тесте — например, тот, что нарочно ломает загрузку куска бандла и
 * смотрит, как вкладка чинит себя. Глушить её на весь набор значило бы
 * ослепить сторожа там, где такая ошибка настоящая.
 */
const expected = new WeakMap()

export function expectConsoleError(page, pattern) {
  expected.set(page, [...(expected.get(page) ?? []), pattern])
}

function interesting(page, text) {
  if (IGNORED.some((pattern) => pattern.test(text))) return false
  return !(expected.get(page) ?? []).some((pattern) => pattern.test(text))
}

export const test = base.extend({
  /** A database in exactly the state `seed_demo` leaves it. */
  seeded: [
    async ({ request }, use) => {
      const response = await request.post('/api/test/reset/')
      expect(
        response.ok(),
        `сброс базы не удался: ${response.status()} ${await response.text()}`,
      ).toBeTruthy()
      await use(true)
    },
    { auto: true },
  ],

  page: async ({ page }, use) => {
    const problems = []

    page.on('console', (message) => {
      if (message.type() !== 'error') return
      problems.push(`console: ${message.text()}`)
    })

    page.on('pageerror', (error) => {
      problems.push(`pageerror: ${error.message}`)
    })

    await use(page)

    // фильтруем в конце, а не на событии: `expectConsoleError` тест зовёт
    // тогда, когда ему удобно, и ошибка может успеть прилететь раньше
    expect(
      problems.filter((text) => interesting(page, text)),
      'браузер сообщил об ошибках',
    ).toEqual([])
  },

  /**
   * Sign in as one of the seeded people, by email.
   *
   * Through the flagged test endpoint, not through Google — a headless
   * browser cannot pass that, and the alternative would be mocking the
   * provider, which tests the mock. The token goes into localStorage exactly
   * where `App.jsx` reads it, before the first script runs.
   */
  signIn: async ({ page, request }, use) => {
    await use(async (email) => {
      const response = await request.post('/api/test/login/', { data: { email } })
      expect(
        response.ok(),
        `вход как ${email} не удался: ${response.status()}`,
      ).toBeTruthy()

      const { key } = await response.json()
      await page.addInitScript(
        ([token]) => window.localStorage.setItem('authToken', token),
        [key],
      )
      return key
    })
  },

  /** Call the API as somebody, for arranging state a test needs. */
  api: async ({ request }, use) => {
    await use(async (email) => {
      const response = await request.post('/api/test/login/', { data: { email } })
      const { key } = await response.json()

      const call = async (method, path, data) => {
        const answer = await request.fetch(path, {
          method,
          headers: { Authorization: `Token ${key}` },
          ...(data ? { data } : {}),
        })
        return { status: answer.status(), body: await answer.json().catch(() => null) }
      }

      return {
        get: (path) => call('GET', path),
        post: (path, data) => call('POST', path, data),
        patch: (path, data) => call('PATCH', path, data),
        put: (path, data) => call('PUT', path, data),
        delete: (path) => call('DELETE', path),
      }
    })
  },
})

export { expect }

/**
 * Число в плашке плана — «в плане» по умолчанию.
 *
 * По тексту плашку не поймать: подписи переводятся, а якорь `data-card`
 * от языка не зависит.
 */
export const lessonCount = (page, card = 'lessons') =>
  page.locator(`[data-card="${card}"] :is(h2, b)`)

/**
 * Курс на живом годе с одним записанным занятием.
 *
 * Записать можно только прошедший час, а год посеянных данных начинается
 * первого сентября — прошедших часов в нём нет ни одного, и раньше эти
 * тесты обходили правило тем, что сервер принимал любую дату. Теперь не
 * принимает: очередь записи строгая, и будущее в неё не входит.
 *
 * Поэтому курс собирается через настоящее API: год вокруг сегодня, курс,
 * назначение, три строки плана, три часа — позавчера, вчера и сегодня, — и
 * запись за первым из них. Ничего закулисного тут нет, ровно те же запросы
 * делает человек руками.
 */
/*
 * Живой курс: год вокруг сегодня, три часа подряд и запись на первом.
 *
 * Часы стоят на **подряд идущих** днях — позавчера, вчера, сегодня, — и это
 * не то же самое, что «в одной неделе»: неделя начинается с понедельника, и
 * во вторник позавчерашний час лежит уже в прошлой. Сетка расписания
 * показывает одну неделю, поэтому тест, который смотрит на два таких часа,
 * обязан перейти к каждому — иначе он проходит по понедельникам и падает по
 * вторникам, а выглядит это как случайная поломка.
 */
export async function liveCourse(api, { record = true } = {}) {
  const admin = await api(PEOPLE.admin)
  const teacher = await api(PEOPLE.ivanova)

  const day = (shift) => {
    const at = new Date()
    at.setDate(at.getDate() + shift)
    return at.toISOString().slice(0, 10)
  }

  const year = await admin.post('/api/calendar/years/', {
    name: `живой ${Date.now()}`,
    start_date: day(-60),
    end_date: day(60),
    weekend_days: [],
  })
  expect(year.status, JSON.stringify(year.body)).toBe(201)

  const course = await admin.post('/api/courses/', {
    name: `Живой курс ${year.body.id}`,
    year: year.body.id,
  })
  expect(course.status, JSON.stringify(course.body)).toBe(201)
  const members = await admin.get('/api/school/members/')
  const assigned = await admin.post('/api/school/assignments/', {
    course: course.body.id,
    teacher: members.body.find((person) => person.email === PEOPLE.ivanova).id,
  })
  expect(assigned.status, JSON.stringify(assigned.body)).toBe(201)

  const rows = []
  for (const title of ['Первый урок', 'Второй урок', 'Третий урок']) {
    const row = await teacher.post('/api/plan/', { course: course.body.id, title })
    expect(row.status, JSON.stringify(row.body)).toBe(201)
    rows.push(row.body)
  }

  const slots = []
  for (const shift of [-2, -1, 0]) {
    const slot = await teacher.post('/api/slots/', {
      course: course.body.id,
      date: day(shift),
      lesson_number: 1,
    })
    expect(slot.status, JSON.stringify(slot.body)).toBe(201)
    slots.push(slot.body)
  }

  if (record) {
    const done = await teacher.patch(`/api/slots/${slots[0].id}/`, {
      lesson: rows[0].id,
    })
    expect(done.status, JSON.stringify(done.body)).toBe(200)
  }

  return { course: course.body, rows, slots, teacher }
}

/**
 * Пункт меню «⋯» в панели плана.
 *
 * Редкое — обмен файлами, полка, отправка на утверждение — живёт под
 * многоточием, как отмена занятия на странице урока. Тестам от этого нужен
 * один лишний клик, и пусть он будет в одном месте.
 */
export async function planMenu(page, name) {
  // Меню над таблицей два — «Файл» и «Библиотека», — и тест называет
  // только пункт: какое из них его держит, знает эта функция. Иначе каждый
  // вызов повторял бы раскладку меню, и переезд пункта правился бы в
  // двадцати местах.
  const menu = /библиотек/i.test(String(name)) ? 'Библиотека' : 'Файл'

  await page.getByRole('button', { name: menu, exact: true }).click()
  await page.locator('.plan-menu .dropdown').getByRole('button', { name }).click()
}

/**
 * Ответить на вопрос, который встаёт после броска: разовый это перенос или
 * постоянная правка расписания.
 *
 * Живёт в оснастке ради одной строки — **паузы**, и она не про медленный
 * стенд. Начав жест, dnd-kit вешает на документ перехват `click` в фазе
 * захвата и снимает его через 50 мс после броска (`detach`, `setTimeout`):
 * так гасится тот самый клик, которым жест закончился, — иначе каждый
 * перенос заканчивался бы ещё и открытым меню клетки.
 *
 * Человеку эти 50 мс незаметны — быстрее никто не отпускает и не нажимает,
 * — а тест успевает нажать через десять, и нажатие пропадает молча: меню
 * остаётся открытым, перенос не случается, и падает потом совсем другое
 * утверждение. Пауза здесь одна на оба набора, вместе с этим объяснением.
 */
export async function pickMoveMode(page, name) {
  await page.waitForTimeout(150)
  await page.locator('.context-menu').getByRole('button', { name }).click()
}

/** The seeded cast, so tests name people rather than addresses. */
export const PEOPLE = {
  admin: 'director@example.com',
  ivanova: 'ivanova@example.com',
  petrov: 'petrov@example.com',
  // второй вид пользователя: у него другой интерфейс целиком
  student: 'stepanov@example.com',
  // второй ученик того же курса: им проверяется, что чужого не видно
  otherStudent: 'volkova@example.com',
  removedStudent: 'morozova@example.com',
  // суперпользователь: два раздела, недостижимых изнутри школы, — список
  // школ и обращения пользователей
  developer: 'developer@example.com',
}

/**
 * Wait for the interface to have finished talking to the server.
 *
 * Pages load their data in `useEffect`, so «the heading is there» does not
 * mean «the list is». Waiting on a visible consequence beats any sleep, and
 * this helper keeps the wait in one place.
 */
export async function ready(page) {
  await expect(page.locator('.topbar')).toBeVisible()
  await page.waitForLoadState('networkidle')
}
