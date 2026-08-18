import { lazy } from 'react'

/**
 * Ленивый кусок бандла, переживающий выкатку.
 *
 * Куски Vite нумерует хэшем содержимого (`LessonPanel-BdvL7dqq.js`), и после
 * выкатки имена меняются. Вкладка, открытая до неё, держит **прежний**
 * `index.html` и просит кусок с прежним именем — а его на сервере уже нет.
 * Сервер отвечает `index.html` (обычный SPA-фолбэк), браузер видит HTML
 * вместо модуля и отказывается его исполнять: «Failed to load module script:
 * expected a JavaScript module but the server responded with text/html».
 * Дальше падает ленивый импорт, и человек получает экран «страница не
 * отрисовалась» на ровном месте — на проде это и случилось.
 *
 * Лечится это перезагрузкой: она берёт свежий `index.html` с новыми именами
 * кусков, и всё встаёт на место. Поэтому здесь **один** повтор через
 * перезагрузку, а не бесконечный: если кусок не грузится по-настоящему
 * (сеть, битая сборка), второй раз мы уже не перезагружаемся, а честно
 * отдаём ошибку наверх — иначе получилась бы вкладка, перезагружающаяся
 * вечно.
 *
 * Отметка живёт в `sessionStorage`: она про эту вкладку и про этот заход, а
 * не про человека. Приватный режим её может не дать — тогда работаем без
 * защиты от повтора, но перезагрузка всё равно случится не чаще, чем
 * ломается импорт.
 */

const KEY = 'chunkReloadedAt'

// столько ждём, прежде чем считать следующий отказ новым случаем, а не
// вторым кругом того же
const QUIET_MS = 30_000

/** Когда последний раз перезагружались из-за куска; 0 — никогда. */
function lastReload() {
  try {
    return Number(window.sessionStorage.getItem(KEY)) || 0
  } catch {
    return 0
  }
}

function rememberReload(now) {
  try {
    window.sessionStorage.setItem(KEY, String(now))
  } catch {
    // приватный режим: обойдёмся без отметки
  }
}

/** Стоит ли перезагружаться: первый отказ за последние полминуты. */
export function shouldReload(now, last) {
  return !last || now - last > QUIET_MS
}

export function lazyChunk(load) {
  return lazy(() =>
    load().catch((error) => {
      const now = Date.now()
      if (!shouldReload(now, lastReload())) throw error

      rememberReload(now)
      window.location.reload()

      // страница уже уходит: промис, который никогда не разрешится, держит
      // Suspense на месте и не даёт мигнуть экраном ошибки перед уходом
      return new Promise(() => {})
    }),
  )
}
