/**
 * graph — the lamina's own wiring, laid out.
 *
 * Every edge here is read from the XML rather than drawn by hand: a function
 * declares its `inputs` and its `output`, an attribute declares `depends_on`,
 * an outcome names the attribute it judges, a tag names the outcome it fires
 * off and the composites it fans into, and a composite lists its members.
 * Follow those five declarations and the picture assembles itself — including
 * the part that matters most, the return path that makes this a loop rather
 * than a pipeline.
 *
 * The layout is two bands:
 *
 *     inputs ─▶ function ─▶ computed ─▶ outcome          forward chain
 *                  ▲                        │
 *                  └──── composite ◀── tag ─┘            correction returning
 *
 * Nothing is positioned by hand. Forward depth is a longest-path layering from
 * the raw inputs, which is what makes a lamina nobody has seen before still
 * come out readable: an attribute always sits to the right of everything it is
 * computed from. The return band hangs beneath, under the nodes it connects.
 *
 * Cycles are expected — the whole point of the model is that corrections come
 * back around — so the layering runs to a fixpoint with an iteration cap
 * instead of assuming a DAG.
 */
import type { LaminaIndex } from './schema'

export type NodeKind = 'sensor' | 'function' | 'computed' | 'outcome' | 'tag' | 'composite'

export interface GraphNode {
  key: string
  kind: NodeKind
  /** The XML id this node stands for — attribute, function, outcome, tag… */
  id: string
  label: string
  sublabel: string
  /** Attribute this node reports a live value for, if any. */
  valueOf?: string
  layer: number
  x: number
  y: number
  w: number
  h: number
}

export type EdgeKind = 'flow' | 'judge' | 'emit' | 'fanout' | 'correct'

export interface GraphEdge {
  key: string
  from: string
  to: string
  kind: EdgeKind
  /** Tag id an edge belongs to, so a firing tag can light its whole path. */
  tag?: string
  path: string
}

export interface TwinGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  byKey: Record<string, GraphNode>
  width: number
  height: number
}

// Geometry.  Every node is the same size; what varies is how many columns a
// layer needs.  A lamina with a dozen raw inputs would otherwise make the first
// layer twelve rows tall and the whole graph unreadably letterboxed, so a layer
// past MAX_ROWS wraps into side-by-side sub-columns instead of growing down.
const NODE_W = 128
const NODE_H = 38
const SUB_GAP = 12
const COL_GAP = 46
const ROW = NODE_H + 12
const BAND_GAP = 40
const PAD = 12
const MAX_ROWS = 6

const keyOf = (kind: NodeKind, id: string) => `${kind}:${id}`

/**
 * Longest-path layering over attributes and functions.
 *
 * Raw inputs sit at 0; everything else is one past the deepest thing it reads.
 * Iterated to a fixpoint rather than topologically sorted, because a lamina may
 * legitimately declare a cycle and a topological sort would simply refuse it.
 */
function layerForwardChain(index: LaminaIndex): Record<string, number> {
  const layer: Record<string, number> = {}
  for (const a of index.sensors) layer[keyOf('sensor', a.id)] = 0

  const attrKey = (id: string) =>
    index.attribute(id)?.source === 'SENSOR' ? keyOf('sensor', id) : keyOf('computed', id)

  for (let pass = 0; pass < 64; pass++) {
    let moved = false
    const raise = (key: string, to: number) => {
      if ((layer[key] ?? -1) < to) {
        layer[key] = to
        moved = true
      }
    }

    for (const fn of index.functions) {
      let deepest = -1
      for (const input of fn.inputs ?? []) deepest = Math.max(deepest, layer[attrKey(input)] ?? 0)
      raise(keyOf('function', fn.id), deepest + 1)
    }

    for (const a of index.computed) {
      const producer = index.functionByOutput[a.id]
      if (producer) {
        raise(keyOf('computed', a.id), (layer[keyOf('function', producer.id)] ?? 0) + 1)
      } else {
        // No function claims it. Place it past whatever it says it depends on
        // so an under-declared lamina still lays out rather than piling up at 0.
        let deepest = -1
        for (const dep of a.depends_on ?? []) deepest = Math.max(deepest, layer[attrKey(dep)] ?? 0)
        raise(keyOf('computed', a.id), deepest + 1)
      }
    }

    for (const o of index.outcomes) {
      raise(keyOf('outcome', o.id), (layer[attrKey(o.attribute_id)] ?? 0) + 1)
    }

    if (!moved) break
  }

  return layer
}

export function buildGraph(index: LaminaIndex): TwinGraph {
  const layer = layerForwardChain(index)
  const nodes: GraphNode[] = []

  const add = (
    kind: NodeKind,
    id: string,
    label: string,
    sublabel: string,
    lyr: number,
    valueOf?: string
  ) => {
    const node: GraphNode = {
      key: keyOf(kind, id),
      kind,
      id,
      label,
      sublabel,
      valueOf,
      layer: lyr,
      x: 0,
      y: 0,
      w: NODE_W,
      h: NODE_H,
    }
    nodes.push(node)
    return node
  }

  // ── Forward band, in the order the model itself declares things ───────────
  for (const a of index.sensors) {
    add('sensor', a.id, a.id, a.unit, layer[keyOf('sensor', a.id)] ?? 0, a.id)
  }
  for (const fn of index.functions) {
    add('function', fn.id, fn.name, fn.formula, layer[keyOf('function', fn.id)] ?? 1)
  }
  for (const a of index.computed) {
    add('computed', a.id, a.id, a.unit, layer[keyOf('computed', a.id)] ?? 1, a.id)
  }
  for (const o of index.outcomes) {
    add(
      'outcome',
      o.id,
      o.id,
      `${o.target_value} ± ${o.tolerance} ${o.unit}`,
      layer[keyOf('outcome', o.id)] ?? 2
    )
  }

  // Rows within a layer follow declaration order, which keeps a re-fetch of
  // the same schema pixel-identical.  Layers are walked in order and each one
  // advances the pen by however many sub-columns it needed.
  const byLayer = new Map<number, GraphNode[]>()
  for (const n of nodes) {
    if (!byLayer.has(n.layer)) byLayer.set(n.layer, [])
    byLayer.get(n.layer)!.push(n)
  }

  let pen = PAD
  let tallest = 1
  const layerOrder = [...byLayer.keys()].sort((a, b) => a - b)
  for (const l of layerOrder) {
    const list = byLayer.get(l)!
    const cols = Math.ceil(list.length / MAX_ROWS)
    const perCol = Math.ceil(list.length / cols)
    list.forEach((n, i) => {
      n.x = pen + Math.floor(i / perCol) * (NODE_W + SUB_GAP)
      n.y = PAD + (i % perCol) * ROW
    })
    tallest = Math.max(tallest, perCol)
    pen += cols * (NODE_W + SUB_GAP) - SUB_GAP + COL_GAP
  }
  const forwardRight = pen - COL_GAP
  const forwardBottom = PAD + tallest * ROW

  // ── Return band ───────────────────────────────────────────────────────────
  // Tags first, then composites beneath them: that is the direction the
  // correction travels, so the picture is read anticlockwise back to the left.
  const byKey: Record<string, GraphNode> = {}
  for (const n of nodes) byKey[n.key] = n

  const tagY = forwardBottom + BAND_GAP
  const compositeY = tagY + ROW

  index.tags.forEach((t, i) => {
    const outcome = byKey[keyOf('outcome', t.outcome)]
    const node = add(
      'tag',
      t.id,
      t.id,
      `${t.gate_kernel} · ${t.emitter}`,
      outcome?.layer ?? layerOrder[layerOrder.length - 1] ?? 0
    )
    node.x = outcome ? outcome.x : PAD + i * (NODE_W + SUB_GAP)
    node.y = tagY
  })

  index.composites.forEach((c, i) => {
    // Sits under the middle of its own members, so the fanout edges stay short
    // and a composite reads as belonging to the attributes it groups.
    const members = (c.attribute_ids ?? [])
      .map((id) => byKey[keyOf('sensor', id)] ?? byKey[keyOf('computed', id)])
      .filter(Boolean)
    const cx = members.length
      ? members.reduce((sum, m) => sum + m.x, 0) / members.length
      : PAD + i * (NODE_W + SUB_GAP)
    const node = add('composite', c.id, c.name, `${(c.attribute_ids ?? []).length} attributes`, 0)
    node.x = cx
    node.y = compositeY
  })

  // Both return-band rows place nodes under something in the forward band, and
  // two outcomes judged in the same column put their tags at the same x — as do
  // two composites whose members overlap. Left as-is the boxes sit exactly on
  // top of each other and the second one is invisible, so each row is swept
  // left to right and anything too close is pushed along.
  spread(nodes.filter((n) => n.kind === 'tag'))
  spread(nodes.filter((n) => n.kind === 'composite'))

  for (const n of nodes) byKey[n.key] = n

  // ── Edges ─────────────────────────────────────────────────────────────────
  const edges: GraphEdge[] = []
  const link = (from: string, to: string, kind: EdgeKind, tag?: string) => {
    const a = byKey[from]
    const b = byKey[to]
    if (!a || !b) return
    edges.push({
      key: `${kind}:${from}->${to}`,
      from,
      to,
      kind,
      tag,
      path: kind === 'flow' || kind === 'judge' ? forwardPath(a, b) : returnPath(a, b),
    })
  }

  const attrKey = (id: string) =>
    index.attribute(id)?.source === 'SENSOR' ? keyOf('sensor', id) : keyOf('computed', id)

  for (const fn of index.functions) {
    for (const input of fn.inputs ?? []) link(attrKey(input), keyOf('function', fn.id), 'flow')
    if (fn.output) link(keyOf('function', fn.id), attrKey(fn.output), 'flow')
  }
  for (const o of index.outcomes) {
    link(attrKey(o.attribute_id), keyOf('outcome', o.id), 'judge')
  }
  for (const t of index.tags) {
    link(keyOf('outcome', t.outcome), keyOf('tag', t.id), 'emit', t.id)
    for (const target of t.targets ?? []) {
      link(keyOf('tag', t.id), keyOf('composite', target.address), 'fanout', t.id)
    }
  }
  for (const c of index.composites) {
    for (const id of c.attribute_ids ?? []) {
      // Where the correction actually lands: X'' is written onto these
      // attributes, which is the step that closes the loop.
      link(keyOf('composite', c.id), attrKey(id), 'correct')
    }
  }

  // Wide enough for the forward band or for however far the composites were
  // nudged, whichever ran further right.
  const width =
    PAD +
    Math.max(forwardRight, ...nodes.map((n) => n.x + n.w)) +
    PAD
  const height = compositeY + NODE_H + PAD
  return { nodes, edges, byKey, width, height }
}

/** Push a row of nodes apart in place, keeping their left-to-right order. */
function spread(row: GraphNode[]): void {
  const sorted = [...row].sort((a, b) => a.x - b.x)
  for (let i = 1; i < sorted.length; i++) {
    const min = sorted[i - 1].x + NODE_W + SUB_GAP
    if (sorted[i].x < min) sorted[i].x = min
  }
}

/** Left-to-right bezier: out of one node's right edge, into the next's left. */
function forwardPath(a: GraphNode, b: GraphNode): string {
  const x1 = a.x + a.w
  const y1 = a.y + a.h / 2
  const x2 = b.x
  const y2 = b.y + b.h / 2
  const dx = Math.max(24, (x2 - x1) * 0.55)
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
}

/** Vertical bezier for the return path, so it reads as coming back around. */
function returnPath(a: GraphNode, b: GraphNode): string {
  const x1 = a.x + a.w / 2
  const x2 = b.x + b.w / 2
  const goingUp = b.y < a.y
  const y1 = goingUp ? a.y : a.y + a.h
  const y2 = goingUp ? b.y + b.h : b.y
  const dy = Math.max(28, Math.abs(y2 - y1) * 0.5) * (goingUp ? -1 : 1)
  return `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`
}

/**
 * Everything one node touches, for hover isolation.  A graph this dense is
 * unreadable without it, and "what feeds this, what does it feed" is the
 * question a viewer actually has.
 */
export function neighbourhood(graph: TwinGraph, key: string | null): Set<string> | null {
  if (!key) return null
  const keep = new Set<string>([key])
  for (const e of graph.edges) {
    if (e.from === key) keep.add(e.to)
    if (e.to === key) keep.add(e.from)
  }
  return keep
}
