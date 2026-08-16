/**
 * Переключатели вида, переживающие перезагрузку.
 *
 * Обычное веб-приложение, ограничений на хранилище нет; чтение и запись
 * обёрнуты в try — в приватном режиме просто не запоминается.
 *
 * Лежит отдельным модулем, потому что флажки разошлись по трём файлам:
 * «Даты», «Недели» и «Свободные» стоят над таблицей и живут в `Plan.jsx`,
 * развёрнутость хвоста свободных слотов нужна только самой таблице, а
 * «Темы уроков» — сводному расписанию.
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

/**
 * Последний выбранный курс — не переключатель вида, а место работы.
 *
 * У учителя музыки полтора десятка курсов, и открывать план всегда на
 * первом по алфавиту значит заставлять его выбирать заново каждый заход.
 * Ключ один на все страницы: работают обычно в одном курсе, и «план 7Б, а
 * работы 5А» — состояние, которого никто не просил.
 */
export function lastChoice(key) {
  try {
    const saved = localStorage.getItem(key)
    return saved === null ? null : Number(saved) || null
  } catch {
    return null
  }
}

export function rememberChoice(key, value) {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    // приватный режим — просто не запоминаем
  }
}
