import { PEOPLE, ready, test } from './harness.js'

test('снимок', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  const work = page.locator('.work-list .course-row', { hasText: 'Контрольная' })
  await work.locator('.toggle').click()
  await work.getByRole('button', { name: 'Проверка' }).click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: '/e2e/shot-dense.png', fullPage: true })
  await page.locator('.work-table thead button.link').nth(1).click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: '/e2e/shot-dense-column.png' })
})
