/**
 * Дерево условий поиска: чистые действия над ним.
 *
 * Живёт отдельно от редактора, потому что правило тут одно и оно не про
 * отрисовку: **пустая группа — не условие**. Сервер такую отклоняет намеренно
 * (группа без содержимого внутри настоящего выражения это опечатка, а не
 * «ничего»), а на экране она возникает сама собой: человек убрал последнюю
 * строку и ещё не вписал новую. Отправить её значило бы показать красный отказ
 * посреди правки — за то, что человек ещё не закончил.
 */

/** Пустые группы прочь; пустое дерево целиком — `null`, то есть «без условий». */
export function prune(node) {
  if (!node || typeof node !== 'object') return null

  const key = 'all' in node ? 'all' : 'any' in node ? 'any' : null
  if (key) {
    const parts = (node[key] || []).map(prune).filter(Boolean)
    if (parts.length === 0) return null
    // Группа из одного условия — это само условие: лишний уровень ничего не
    // значит ни для поиска, ни для чтения.
    if (parts.length === 1) return parts[0]
    return { [key]: parts }
  }

  if ('not' in node) {
    const inner = prune(node.not)
    return inner ? { not: inner } : null
  }

  if ('text' in node) return String(node.text).trim() ? { text: node.text } : null
  if ('tag' in node && node.tag) return node

  return null
}
