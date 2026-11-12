// Groups the bell's drop notifications that arrived close together, so five
// drops in one check read as one row. Pure: no dates beyond created_at.

const isDrop = (n) => /_drop$/.test(n?.kind || '') && n?.data?.drop?.observed !== false

const ms = (n) => {
  const v = Date.parse(n?.created_at)
  return Number.isFinite(v) ? v : null
}

/**
 * groupDrops(notifications, windowMin) -> Array<{ids, kind, count, latest}>
 *
 * `notifications` is newest first and the result keeps that order (a group sits
 * where its newest item is). Only drop notifications of the same kind merge,
 * and only when each one is within `windowMin` minutes of the previous one in
 * its group. A window of 0 (or less) merges nothing. Everything else is a
 * group of one.
 */
export function groupDrops(notifications, windowMin = 15) {
  const out = []
  const open = {}   // kind -> the group still accepting older items
  const span = Number(windowMin) > 0 ? Number(windowMin) * 60000 : 0
  for (const n of notifications || []) {
    const at = ms(n)
    const g = isDrop(n) && span && at != null ? open[n.kind] : null
    if (g && g.oldest != null && g.oldest - at <= span && g.oldest - at >= 0) {
      g.ids.push(n.id)
      g.count += 1
      g.oldest = at
      continue
    }
    const group = { ids: [n.id], kind: n.kind, count: 1, latest: n, oldest: at }
    out.push(group)
    if (isDrop(n) && span) open[n.kind] = group
  }
  return out.map(({ oldest: _oldest, ...g }) => g)
}
