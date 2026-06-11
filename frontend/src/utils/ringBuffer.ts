/**
 * Push an item onto an immutable ring buffer (plain array).
 * Returns a new array — safe to drop directly into React state.
 * Oldest item is dropped when length exceeds capacity.
 */
export function pushRing<T>(buf: readonly T[], item: T, capacity: number): T[] {
  const next = [...buf, item]
  return next.length > capacity ? next.slice(-capacity) : next
}
