import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Личный стол: папки слева, вещи справа, и ничего чужого.
 *
 * Питоновский набор проверяет права и то, что вложение с пятым владельцем
 * заводится; здесь проверяется то, чего он увидеть не может, — что раздел
 * **собран** и что круг «положил → нашёл → переложил» замыкается в живом
 * браузере. Загрузка файла сюда не входит и войти не может: у стенда нет
 * хранилища объектов, а ссылка и записка проходят весь путь целиком.
 *
 * Второй тест здесь — про чужое, и он важнее первого. Ошибка в личном
 * разделе выглядит не как сломанная кнопка, а как чужие записки в своём
 * списке, и заметить её глазами на своей же машине нельзя.
 */

test('учитель кладёт ссылку и записку, находит их поиском и перекладывает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bookmarks')
  await ready(page)

  // папка заводится и сразу открывается: её и заводят, когда есть что класть
  await page.getByLabel('Новая папка').fill('Экскурсии')
  await page.locator('.shelf aside').getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.shelf-pick.active')).toContainText('Экскурсии')

  // ссылка: вид решает написанное, поэтому рядом появляется поле названия
  await page.getByLabel('Адрес или записка').fill('https://example.org/museum')
  await page.getByLabel('Название ссылки').fill('Музей: заявка на класс')
  await page.getByLabel('Приписка').fill('Заявку подают за две недели')
  await page.locator('.shelf-add').getByRole('button', { name: 'Добавить' }).click()

  const items = page.locator('.shelf-item')
  await expect(items).toHaveCount(1)
  await expect(items.first()).toContainText('Музей: заявка на класс')
  await expect(items.first().locator('.note')).toContainText('за две недели')
  await expect(items.first().locator('a')).toHaveAttribute(
    'href',
    'https://example.org/museum',
  )

  // записка: адресом это не является, значит вид другой и поля названия нет
  await page.getByLabel('Адрес или записка').fill('Автобус заказывает завхоз')
  await expect(page.getByLabel('Название ссылки')).toHaveCount(0)
  await page.locator('.shelf-add').getByRole('button', { name: 'Добавить' }).click()
  await expect(items).toHaveCount(2)

  // поиск идёт по всему столу, а не по открытой папке: посеянная закладка
  // лежит в другой, и найтись обязана всё равно
  await page.getByLabel('Найти у себя').fill('Десмос')
  await expect(items).toHaveCount(1)
  await expect(items.first()).toContainText('Десмос')

  await page.getByLabel('Найти у себя').fill('')

  // переложить — правка ссылки, а не вторая загрузка: у строки для этого
  // есть папка прямо в форме правки
  await items.first().getByTitle('Изменить').click()
  await page.getByLabel('Папка', { exact: true }).selectOption({ label: 'Без папки' })
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await page.locator('.shelf-pick', { hasText: 'Без папки' }).click()
  await expect(page.locator('.shelf-item').first()).toContainText(
    'Музей: заявка на класс',
  )
})

test('снос папки оставляет лежавшее в ней на столе', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bookmarks')
  await ready(page)

  page.on('dialog', (dialog) => dialog.accept())

  const folder = page.locator('.shelf-pick', { hasText: 'Методика' })
  await folder.click()
  const inside = await page.locator('.shelf-item').count()
  expect(inside).toBeGreaterThan(0)

  await page.getByRole('button', { name: 'Удалить' }).click()

  await expect(page.locator('.shelf-pick', { hasText: 'Методика' })).toHaveCount(0)
  // вещи не исчезли вместе с папкой — они на столе, и стол их показывает
  await page.locator('.shelf-pick', { hasText: 'Всё' }).first().click()
  await expect(page.locator('.shelf-item')).toContainText(['Десмос'])
})

test('чужого стола не видно даже директору', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await page.goto('/bookmarks')
  await ready(page)

  // у директора свой стол, посеянный отдельно, и в нём его собственное
  await expect(page.locator('.shelf-pick', { hasText: 'Педсовет' })).toBeVisible()
  await expect(page.locator('.shelf-pick', { hasText: 'Методика' })).toHaveCount(0)

  await page.locator('.shelf-pick', { hasText: 'Всё' }).first().click()
  await expect(page.locator('.shelf-item')).not.toContainText(['Десмос'])
})

test('ученику раздела не показывают вовсе', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await expect(page.locator('.topbar-nav a[href="/bookmarks"]')).toHaveCount(0)
})
