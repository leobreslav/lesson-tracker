import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Переписка: список собеседников слева, разговор справа, строка внизу.
 *
 * Проверяется здесь то, чего питоновский набор не ловит по построению — что
 * экран **есть у обеих сторон**. Дыра, с которой всё началось, была ровно
 * такой: сервер отвечал и родителю, и учителю, а смонтирован экран был только
 * у родителя, и учитель не мог ни прочитать сообщение, ни ответить.
 */

test('учитель пишет коллеге, и тот читает это у себя', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/talks')
  await ready(page)

  // Собеседник называется по имени, а не берётся первым попавшимся: список
  // отсортирован по фамилии, и «первый» — это директор, а проверяем мы
  // разговор двух учителей.
  const petrov = page.locator('.chat-pick', { hasText: 'Петров' }).first()
  await expect(petrov).toBeVisible()
  await petrov.click()

  await page.getByRole('textbox', { name: 'сообщение' }).fill('Зайдёшь на педсовет?')
  await page.getByRole('button', { name: 'Отправить' }).click()

  await expect(page.locator('.chat-message').last()).toContainText(
    'Зайдёшь на педсовет?',
  )

  // и то же самое видно второй стороне — тем же экраном, а не другим
  await signIn(PEOPLE.petrov)
  await page.goto('/talks')
  await ready(page)

  const started = page.locator('.chat-pick', { hasText: 'Иванова' }).first()
  await started.click()
  await expect(page.locator('.chat-message').last()).toContainText(
    'Зайдёшь на педсовет?',
  )
})

test('ученик пишет своему учителю, и учитель отвечает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.student)
  await page.goto('/talks')
  await ready(page)

  const teacher = page.locator('.chat-pick').first()
  await expect(teacher).toBeVisible()
  await teacher.click()

  await page.getByRole('textbox', { name: 'сообщение' }).fill('Можно пересдать?')
  await page.getByRole('button', { name: 'Отправить' }).click()
  await expect(page.locator('.chat-message').last()).toContainText('Можно пересдать?')

  await signIn(PEOPLE.ivanova)
  await page.goto('/talks')
  await ready(page)

  // непрочитанное видно счётчиком: ради него список и заведён
  await expect(page.locator('.chat-list .unread').first()).toBeVisible()
})

test('переписка открывается из бара', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)

  await page.getByRole('link', { name: 'Переписка' }).click()
  await ready(page)

  await expect(page).toHaveURL(/\/talks$/)
  // список собеседников слева есть всегда: писать коллегам можно и без курсов
  await expect(page.locator('.chat-list')).toBeVisible()
})
