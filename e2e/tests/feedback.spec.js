import { PEOPLE, expect, expectConsoleError, ready, test } from './harness.js'

/**
 * Сценарий: сказать разработчику — и увидеть сказанное.
 *
 * Путь идёт через два интерфейса и две роли, и ровно поэтому его стоит гнать
 * браузером: учитель пишет из своего бара, ученик — из своего, а читает
 * обоих третий человек, которого нет ни в одной школе. Ни один питоновский
 * тест этой цепочки целиком не видит.
 */

const open = async (page, path) => {
  await page.goto(path)
  await ready(page)
}

test('учитель пишет об ошибке, разработчик это видит', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await open(page, '/schedule')

  await page.getByRole('button', { name: 'Написать' }).click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toBeVisible()
  // вид обращения — тумблер, а не две кнопки: это один выбор
  await expect(dialog.getByRole('radio', { name: 'Ошибка' })).toBeChecked()
  await dialog
    .getByLabel('Что случилось')
    .fill('Неделя не листается назад дальше сентября')
  await dialog.getByRole('button', { name: 'Отправить' }).click()

  // ответа здесь не будет, и окно говорит об этом прямо
  await expect(dialog).toContainText('ответом станет починка')
  // выход один — крестик: кнопка, которая просто уводит, из окон убрана
  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(dialog).toBeHidden()

  // читает написанное суперпользователь — и только он
  await signIn(PEOPLE.developer)
  await open(page, '/feedback')

  const row = page.locator('.feedback-list li', {
    hasText: 'Неделя не листается назад',
  })
  await expect(row).toBeVisible()
  await expect(row).toContainText('Мария Иванова')
  // адрес страницы приезжает сам: без него «тут не работает» искать негде
  await expect(row).toContainText('/schedule')

  // разобранное уходит из очереди, но не пропадает.
  // Проверяем **свою** строку, а не длину списка: посев кладёт в очередь свои
  // обращения, и «ноль строк» было утверждением про пустую базу, а не про
  // механизм. Первое же чужое сообщение сделало бы его ложным.
  await row.getByRole('button', { name: 'Разобрано' }).click()
  await expect(row).toHaveCount(0)

  await page.getByRole('radio', { name: 'Разобранные' }).click()
  await expect(
    page.locator('.feedback-list li', { hasText: 'Неделя не листается назад' }),
  ).toBeVisible()
})

test('ученику писать тоже есть чем', async ({ page, signIn }) => {
  // Поломку он видит ту же, что учитель, а сказать о ней ему было нечем
  // вовсе: администратор школы интерфейс не чинит, а больше некому.
  await signIn(PEOPLE.student)
  await open(page, '/')

  await page.getByRole('button', { name: 'Написать' }).click()
  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('radio', { name: 'Предложение' }).click()
  await dialog.getByLabel('Что случилось').fill('Хорошо бы видеть свои оценки списком')
  await dialog.getByRole('button', { name: 'Отправить' }).click()
  await expect(dialog).toContainText('Спасибо')

  await signIn(PEOPLE.developer)
  await open(page, '/feedback')

  const row = page.locator('.feedback-list li', { hasText: 'свои оценки списком' })
  await expect(row).toContainText('Предложение')
  await expect(row).toContainText('Артём Степанов')
})

test('раздела обращений у школы нет: он не её', async ({ page, signIn }) => {
  // Жалоба на интерфейс — не школьный документ, и «мой завуч прочитает,
  // что я написал» отбивает желание писать вернее любого отказа.
  await signIn(PEOPLE.admin)
  await open(page, '/')

  await expect(page.getByRole('link', { name: 'Обращения' })).toHaveCount(0)

  // адрес открывается — и получает отказ сервера: прячет раздел бар, а
  // закрывает его вьюха. Отказ ожидаем именно здесь, поэтому и назван
  expectConsoleError(page, /Failed to load resource|403|api\/feedback/)
  await open(page, '/feedback')
  await expect(page.locator('.feedback-list')).toHaveCount(0)
  await expect(page.getByRole('alert')).toBeVisible()
})
