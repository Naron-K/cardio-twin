# Switching laminae from inside the app

Written 2026-08-20 for a later session. Nothing here is implemented yet.

## The problem, measured

Today, changing lamina means stopping the backend and starting it again with a
different `CARDIOTWIN_LAMINA`. That works — `python serve.py respiratory` — but
the browser is not told, and the failure is silent.

Reproduced: a page loaded against `lamina_respiratory`, then the backend swapped
to `lamina_circulatory` underneath it.

```
44:57  header "Respiratory"   V_E 6.08 …      still live
45:03  header "Respiratory"   V_E 6.17 +0.300
45:24  header "Respiratory"   V_E 6.17 +0.300  frozen, and still frozen
```

The socket died with the old process, so the last tick it received stayed on
screen looking exactly like a live one. Reload and everything is correct again.

Two distinct defects sit behind that:

1. **The schema is fetched once, at mount.** Nothing re-reads it, so a page can
   hold one lamina's structure while the socket streams another's values. The
   header keeps naming the old lamina and, where the old lamina had artwork, the
   old artwork keeps being drawn. (This is what makes it *look* like the heart
   fails to separate from the respiratory lamina. It does separate — the stage
   registry has no entry for `lamina_respiratory`, and a freshly loaded page
   shows no heart, no mode toggle and no chamber legend. The heart on screen
   belonged to a schema that was never refreshed.)

2. **A dead socket looks like a live one.** Values freeze at the last tick and
   nothing dims or marks them. The connection chip does flip to Reconnecting,
   but the numbers — which are what anyone is actually reading — do not change
   at all.

## The design

**Make the lamina a property of the connection, not of the process.**

`Session` is already built per WebSocket connection and `/api/schema` already
builds a twin per request; both just happen to read one global path. Passing the
lamina per request removes the restart entirely, lets two tabs run two laminae
at once, and — most importantly — makes it possible to guarantee that the schema
and the stream came from the same place.

`CARDIOTWIN_LAMINA` stays as the default for a request that names none.

## Steps

### Backend

1. **`GET /api/laminae`** — what is available. Scan `backend/*_lamina.xml`, read
   each file's `id` and `name`, and report whether `_IMPLEMENTATIONS` has a class
   for it. A lamina with no implementation is listed and marked, not hidden:
   it loads on bare `UniversalTwin` and draws its structure with a dash on every
   computed node, which is a legitimate thing to want to look at.

2. **`GET /api/schema?lamina=<id>`** — accept the parameter, fall back to
   `lamina_path()`. Resolve by lamina id, not by filename, so the URL does not
   depend on where the file sits. Reject an unknown id with a 404 naming what is
   available, rather than silently serving the default.

3. **`/ws/feedback?lamina=<id>`** — same parameter, same resolution, same
   rejection. `Session(lamina=…)` instead of reading the global.

4. **Every snapshot carries `lamina_id`.** This is the load-bearing change and
   it is one line. Without it the frontend has no way to detect the mismatch;
   with it, the guard in step 7 becomes possible.

5. Tests: two sessions on two laminae at once do not interfere; an unknown id is
   rejected; the snapshot's `lamina_id` matches the schema's for both.

### Frontend

6. **Lamina picker in the header**, fed by `/api/laminae`. Selecting one
   re-fetches the schema *and* reopens the socket, both with the same id — they
   are set together or not at all. Deep link `#twin/<lamina_id>` so a link opens
   the right one and a reload keeps it.

7. **Guard the invariant.** Compare each tick's `lamina_id` against the loaded
   schema's. On mismatch: stop rendering values, say what happened, re-fetch the
   schema for whatever the stream is actually sending. This is what makes the
   whole class of bug impossible rather than merely unlikely — including the
   case where someone restarts the backend behind an already-open tab, which is
   exactly how it was found.

8. **Mark a stale stream.** When the socket is not open, the numbers on screen
   are a photograph. Dim the value columns and stamp the age of the last tick.
   The same rule as the ECG and the simulated feed: a reader should never have
   to work out whether what they are looking at is current.

### Optional, and needs a decision first

9. **Artwork for the respiratory lamina.** The registry already supports it —
   one entry in `stageRegistry.tsx` plus a template directory under `public/` —
   so nothing structural is missing. What is missing is the art. Per the
   standing rule on this project, the art direction is approved before anything
   is drawn; a procedurally generated stage would be the wrong move here as it
   was before. Until then the lamina map is the honest default and it works.

## Order and effort

Steps 1–4 are small and unlock everything else; 7 is the one that actually fixes
the reported symptom and should not be deferred behind the picker. 6 is the
visible feature. 8 is independent of all of it and worth doing regardless. 9 is
a separate conversation about artwork.

## What not to do

Do **not** add a `POST /api/lamina` that mutates a module global. It is smaller
to write and it reintroduces shared mutable state: two tabs would fight over
which lamina the process is on, and the mismatch this plan exists to prevent
would come back through a different door.
