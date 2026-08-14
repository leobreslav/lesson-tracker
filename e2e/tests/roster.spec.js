import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Состав курса: три списка в одном окне и вставка класса целиком.
 *
 * Через браузер это стоит гонять потому, что в одном окне сходятся четыре
 * источника — зачисленные, снятые, приглашённые и то, что предпросмотр
 * обещает сделать со вставкой, — и разъезжаются они молча: числа сойдутся,
 * а список покажет не тех.
 */

const openRoster = async (page, name) => {
  await page.goto('/school/courses')
  await ready(page)

  const card = page.locator('.course-row', { hasText: name })
  await card.locator('.toggle').click()
  await card.getByRole('button', { name: 'Состав и добавление' }).click()

  return page.locator('.modal-body.roster-window')
}

test('в составе курса видно всех троих: учатся, ждут входа и сняты', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  const dialog = await openRoster(page, 'Grade 6 Algebra')

  // пятеро учатся, шестая снята, седьмой приглашён и ни разу не входил
  await expect(dialog.locator('.roster.enrolled li')).toHaveCount(5)
  await expect(dialog.locator('.roster.waiting li')).toHaveCount(1)
  await expect(dialog.locator('.roster.past li')).toHaveCount(1)
  await expect(dialog.locator('.roster.past')).toContainText('Ева Морозова')
  await expect(dialog).toContainText('sokolov@example.com')
})

test('вставка списка считает пятерых по-разному и зачисляет', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  const dialog = await openRoster(page, 'Grade 6 Algebra')

  await dialog.getByLabel('Вставить список').fill(
    [
      'stepanov@example.com', // уже учится
      'morozova@example.com', // снята — вернём
      'Новиков Илья, novikov@example.com', // учётки нет — пригласим
      'petrov@example.com', // учитель — адрес занят
    ].join('\n'),
  )
  await dialog.getByRole('button', { name: 'Проверить' }).click()

  const summary = dialog.locator('[data-roster-preview]')
  await expect(summary).toContainText('Зачислим: 0')
  await expect(summary).toContainText('вернём: 1')
  await expect(summary).toContainText('пригласим: 1')
  await expect(summary).toContainText('уже в курсе: 1')
  // занятый адрес назван поимённо: «занят один адрес» само по себе загадка
  await expect(dialog).toContainText('petrov@example.com')

  await dialog.getByRole('button', { name: 'Зачислить' }).click()

  // снятая вернулась той же строкой, приглашение уехало в ожидающие
  await expect(dialog.locator('.roster.past li')).toHaveCount(0)
  await expect(dialog.locator('.roster.enrolled')).toContainText('Ева Морозова')
  await expect(dialog).toContainText('Новиков Илья')
})

test('строка, которую не прочитать, отменяет вставку целиком', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  const dialog = await openRoster(page, 'Grade 6 Geometry')

  await dialog
    .getByLabel('Вставить список')
    .fill('Петров Иван\nnovikov@example.com')
  await dialog.getByRole('button', { name: 'Проверить' }).click()

  await expect(dialog).toContainText('Строка 1: нет адреса почты')
  await expect(dialog.getByRole('button', { name: 'Зачислить' })).toBeDisabled()
})
