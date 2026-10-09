/**
 * stageRegistry — the one file in the visualiser allowed to name a lamina.
 *
 * Artwork cannot be derived. Someone drew a heart; nothing in
 * `circulatory_lamina.xml` says a heart is what its attributes look like, and
 * no amount of schema reading will produce a picture of one. So the artwork
 * layer is quarantined here: a single map from lamina id to the artwork that
 * happens to exist for it.
 *
 * Everything else in `twin/` is derived from the schema and works on any
 * lamina. This file is the deliberate exception, kept to one screen so the
 * exception stays visible and small. A lamina with no entry here is not
 * broken — it simply has no stage, and the dashboard puts the lamina map in
 * the centre instead, which is the honest default for a model nobody has
 * illustrated.
 *
 * Adding a lamina's artwork means: drop a template directory under `public/`,
 * add one entry below. No renderer changes.
 */
export interface StageArtwork {
  /** Directory under `public/` holding `template.json` and its cutouts. */
  dir: string
  /** Label for the template-driven view of that artwork. */
  label: string
}

export const STAGE_ARTWORK: Record<string, StageArtwork> = {
  lamina_circulatory: { dir: 'heart', label: 'Anatomical' },
}

export function artworkFor(laminaId: string | undefined): StageArtwork | null {
  if (!laminaId) return null
  return STAGE_ARTWORK[laminaId] ?? null
}
