/**
 * stageRegistry — the one file in the visualiser allowed to name a lamina.
 *
 * Artwork cannot be derived. Someone drew a heart; nothing in
 * `circulatory_lamina.xml` says a heart is what its attributes look like, and
 * no amount of schema reading will produce a picture of one. So the artwork
 * layer is quarantined here: a single map from lamina id to the assets and
 * hand-authored renderers that happen to exist for it.
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
import type { ReactNode } from 'react'
import { PixelHeart } from '../components/twin/PixelHeart'
import type { Chamber } from './heartSprite'

export interface StageRenderProps {
  /** Model-computed attributes only — the same prop the template stage takes. */
  values: Record<string, number>
  paused: boolean
  focus: string | null
  /** An outcome is outside the tolerance the model declared for it. */
  alert: boolean
}

/**
 * A renderer offered alongside the template-driven stage for one lamina only.
 * It reads the same model values through the same rule; what differs is the
 * artwork, which is the point of having a second one at all.
 */
export interface AlternateRenderer {
  id: string
  label: string
  render: (props: StageRenderProps) => ReactNode
}

export interface StageArtwork {
  /** Directory under `public/` holding `template.json` and its cutouts. */
  dir: string
  /** Label for the template-driven view of that artwork. */
  label: string
  alternates: AlternateRenderer[]
}

export const STAGE_ARTWORK: Record<string, StageArtwork> = {
  lamina_circulatory: {
    dir: 'heart',
    label: 'Anatomical',
    alternates: [
      {
        id: 'pixel',
        label: '16-bit',
        // The sprite predates the template system and takes named quantities
        // rather than a bag of values. Translating them is this entry's job —
        // it is lamina-specific knowledge, and this is the lamina-specific
        // file. A missing T_cycle is not a cycle length; the beat clock
        // rejects 0 and holds its current rate until the model supplies one.
        render: ({ values, paused, focus, alert }: StageRenderProps) => (
          <PixelHeart
            cycleSeconds={values.T_cycle ?? 0}
            co={values.CO ?? 0}
            sv={values.SV ?? 0}
            alert={alert}
            paused={paused}
            focus={focus as Chamber | null}
          />
        ),
      },
    ],
  },
}

export function artworkFor(laminaId: string | undefined): StageArtwork | null {
  if (!laminaId) return null
  return STAGE_ARTWORK[laminaId] ?? null
}
