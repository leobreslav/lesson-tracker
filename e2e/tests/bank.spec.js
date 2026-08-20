import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Задачник: источники, условия и решения.
 *
 * Через браузер это гонять надо из-за двух вещей. Первая — **номер как
 * адрес**: учитель помнит «§14, №6», и если поле номера не приводит к задаче,
 * каталогом никто не пользуется. Вторая — **уровни владения**: у чужой книги
 * не должно быть кнопок правки, и увидеть это можно только глазами.
 */

test('книга заводится вставкой, а номер ведёт прямо к задаче', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank')
  await ready(page)

  await page.getByRole('button', { name: 'Добавить источник' }).click()
  await page.getByLabel('Название').fill('Мордкович. Алгебра 9')
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()

  await page.getByRole('link', { name: 'Мордкович. Алгебра 9' }).click()
  await ready(page)

  // оглавление вписывается целиком: по одной главе его не заводит никто
  await page.getByRole('button', { name: 'Вписать оглавление' }).click()
  await page.locator('.modal textarea').fill('Глава 1\n  §14 Квадратные уравнения')
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.outline')).toContainText('§14')

  // задачи — тоже вставкой, номером и табуляцией
  await page.getByRole('button', { name: 'Вписать задачи' }).click()
  await page.locator('.modal textarea').fill('6\t$2x^2+5x-3=0$\n7\tРешите неравенство\n14а\tДокажите тождество')
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.problem-list li')).toHaveCount(3)

  // номер — адрес: он и есть главный путь к задаче
  await page.getByLabel('Номер').fill('14а')
  await expect(page.locator('.problem-list li')).toHaveCount(1)
  await expect(page.locator('.problem-list')).toContainText('Докажите тождество')
})

test('к чужому условию можно написать своё решение', async ({ page, signIn, api }) => {
  // системная книга: её завёл суперпользователь, править её учитель не может
  const root = await api(PEOPLE.admin)
  const teacher = await api(PEOPLE.ivanova)
  const mine = await teacher.post('/api/bank/sources/', {
    title: 'Мои листочки',
    level: 'personal',
  })
  await teacher.post(`/api/bank/sources/${mine.body.id}/`, {
    problems: '1\t$2x^2+5x-3=0$',
  })
  const book = await teacher.get(`/api/bank/sources/${mine.body.id}/`)
  const problem = book.body.entries[0].problem

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/problem/${problem}`)
  await ready(page)

  await expect(page.getByText('Разбора пока никто не написал')).toBeVisible()

  await page.getByRole('button', { name: 'Добавить решение' }).click()
  await page.getByLabel('Метод, в двух словах').fill('Разложением на множители')
  await page.locator('.inline-form textarea').fill('$(2x-1)(x+3)=0$')
  await page.locator('.inline-form').getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.getByText('Разложением на множители')).toBeVisible()
})

test('ученику задачника нет вовсе', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await expect(page.getByRole('link', { name: 'Задачник' })).toHaveCount(0)
})
