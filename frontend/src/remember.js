/**
 * Переключатели вида, переживающие перезагрузку.
 *
 * Обычное веб-приложение, ограничений на хранилище нет; чтение и запись
 * обёрнуты в try — в приватном режиме просто не запоминается.
 *
 * Лежит отдельным модулем, потому что флажки разошлись по двум файлам:
 * «Даты», «Недели» и «Свободные» стоят над таблицей и живут в `Plan.jsx`, а
 * развёрнутость хвоста свободных слотов нужна только самой таблице.
 */

export function remembered(key, fallback) {
  try {
    const saved = localStorage.getItem(key)
    return saved === null ? fallback : saved === '1'
  } catch {
    return fallback
  }
}

export function remember(key, value) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // приватный режим — просто не запоминаем
  }
}
