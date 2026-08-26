# Switching laminae from inside the app

Written 2026-08-20. Steps 1–8 are built; step 9 is still a conversation about
artwork rather than a task.

## The problem, measured

Changing lamina used to mean stopping the backend and starting it again with a
different `CARDIOTWIN_LAMINA`. That worked — `python serve.py respiratory` — but
the browser was not told, and the failure was silent.

Reproduced: a page loaded against `lamina_respiratory`, then the backend swapped
to `lamina_circulatory` underneath it.

```
44:57  header "Respiratory"   V_E 6.08 …      still live
45:03  header "Respiratory"   V_E 6.17 +0.300
45:24  header "Respiratory"   V_E 6.17 +0.300  frozen, and still frozen
```

The socket died with the old process, so the last tick it received stayed on
screen looking exactly like a live one. Reload and everything was correct again.

Two distinct defects sat behind that:

1. **The schema was fetched once, at mount.** Nothing re-read it, so a page
   could hold one lamina's structure while the socket streamed another's values.
   The header kept naming the old lamina and, where the old lamina had artwork,
   the old artwork kept being drawn. (This is what made it *look* like the heart
   failed to separate from the respiratory lamina. It does separate — the stage
   registry has no entry for `lamina_respiratory`, and a freshly loaded page
   shows no heart, no mode toggle and no chamber legend. The heart on screen
   belonged to a schema that was never refreshed.)

2. **A dead socket looked like a live one.** Values froze at the last tick and
   nothing dimmed or marked them. The connection chip did flip to Reconnecting,
   but the numbers — which are what anyone is actually reading — did not change
   at all.

## The design

**The lamina is a property of the connection, not of the process.**

`Session` was already built per WebSocket connection and `/api/schema` already
built a twin per request; both just happened to read one global path. Passing
the lamina per request removes the restart entirely, lets two tabs run two
laminae at once, and — most importantly — makes it possible to guarantee that
the schema and the stream came from the same place.

`CARDIOTWIN_LAMINA` stays as the default for a request that names none.

## What was built

### Backend

1. **`GET /api/laminae`** — what is available. Scans `backend/*_lamina.xml`,
   reads each file's `id`, `name` and `level`, and reports whether
   `_IMPLEMENTATIONS` has a class for it. A lamina with no implementation is
   listed and marked, not hidden: it loads on bare `UniversalTwin` and draws its
   structure with a dash on every computed node, which is a legitimate thing to
   want to look at. `default` names the lamina a request naming none will get.

2. **`GET /api/schema?lamina=<id>`** — accepts the parameter, falls back to
   `lamina_path()`. Resolves by lamina id, not by filename, so the URL does not
   depend on where the file sits. An unknown id is a 404 naming what is
   available, rather than silently serving the default.

3. **`/ws/feedback?lamina=<id>`** — same parameter, same resolution.
   `Session(lamina=…)` instead of reading the global. An unknown id is resolved
   *before* the socket is accepted and closed with 1008 and a reason, so the
   client reports it instead of retrying forever.

4. **Every snapshot carries `lamina_id`.** The load-bearing change, and it is
   one line in `snapshot.py`. Without it the frontend has no way to detect the
   mismatch; with it, the guard in step 7 becomes possible.

5. Tests — `backend/tests/test_lamina_switching.py`, 11 of them: two sessions
   and two open sockets on two laminae at once do not interfere, an unknown id
   is refused on both transports, resolution is by id and not by filename, and
   the snapshot's `lamina_id` matches the schema's for both laminae.

### Frontend

6. **Lamina picker in the header**, fed by `/api/laminae`, falling back to a
   plain label when fewer than two laminae exist. Selecting one re-fetches the
   schema *and* reopens the socket, both with the same id. Deep link
   `#twin/<lamina_id>` so a link opens the right one and a reload keeps it.

7. **The invariant is guarded.** Each tick's `lamina_id` is compared against the
   loaded schema's. On mismatch: no value is rendered at all, the stage says
   what happened, and the schema is re-fetched for whatever the stream is
   actually sending. Verified against the case that produced the report —
   restarting the backend onto the other lamina behind an already-open tab —
   which now converges to the new lamina, URL included, without a reload.

   Both halves are *tagged with the lamina they belong to* rather than cleared
   when it changes: the schema carries the id it was fetched for, the tick
   buffer carries the id it was streamed for, and a tag that no longer matches
   simply is not read. Clearing would leave a render pass in between holding one
   model's numbers under another's labels, which is the bug.

8. **A stale stream is marked.** When the socket is not open, the numbers on
   screen are a photograph: the value columns dim, the inputs disable, and a
   chip stamps the age of the last tick — `Frozen · last tick 3s ago`. The same
   rule as the ECG and the simulated feed: a reader should never have to work
   out whether what they are looking at is current.

## Still open, and needs a decision first

9. **Artwork for the respiratory lamina.** The registry already supports it —
   one entry in `stageRegistry.tsx` plus a template directory under `public/` —
   so nothing structural is missing. What is missing is the art. Per the
   standing rule on this project, the art direction is approved before anything
   is drawn; a procedurally generated stage would be the wrong move here as it
   was before. Until then the lamina map is the honest default and it works.

## What not to do

Do **not** add a `POST /api/lamina` that mutates a module global. It is smaller
to write and it reintroduces shared mutable state: two tabs would fight over
which lamina the process is on, and the mismatch this design exists to prevent
would come back through a different door.

One thing deliberately left alone: the hash is read at mount, not watched. A
link or a reload lands on the right lamina; editing the address bar in place
does not re-route, which is how `#twin` and `#stream` have always behaved.
