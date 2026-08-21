# Nodus frontend

The reading surface for Nodus: submit a question, watch the pipeline run, and read
the report it produces — one section per claim cluster, each carrying where its
evidence came from, where the papers disagree, and how far it can be trusted.

Built from the Claude Design project `Nodus.dc.html` (design system: Modernist).

## Stack

- React 18 + TypeScript, built with Vite
- No UI framework. `src/styles/tokens.css` is the design system imported verbatim;
  `src/styles/base.css` is the Nodus surface on top of it.
- No data-fetching library: the whole API is one WebSocket, and `src/lib/ws.ts` is
  the client for it.

## Running it

```bash
npm install
cp .env.example .env      # fill in VITE_NODUS_WS_URL or NODUS_API_URL
npm run dev               # http://localhost:5173
```

| Script | What it does |
| --- | --- |
| `npm run dev` | dev server, `/api` proxied to `NODUS_API_URL` |
| `npm run build` | typecheck then production build into `dist/` |
| `npm run typecheck` | types only |

### Talking to a backend

The socket URL resolves in this order:

1. `VITE_NODUS_WS_URL` if set — an absolute `wss://…/api/v2/ws`, for a static build
   served from a different origin than the API.
2. Otherwise same-origin `/api/v2/ws`, which the dev server proxies to
   `NODUS_API_URL` (default: the hosted deployment; set it to
   `http://127.0.0.1:8000` for a local `uvicorn`).

Set `VITE_NODUS_API_KEY` when the backend has `API_KEY` set; it is sent as
`?api_key=` on the handshake, which is how the v2 socket authenticates.

### Demo mode

With `VITE_NODUS_DEMO=1`, or whenever no Nodus socket answers, the app runs on a
fixture corpus in `src/data/`: a completed run over 20 papers, three of which
failed extraction. Every screen — including the failure and degenerate states — is
the real UI; only the data is fixture. The sidebar says which mode is in effect,
and never pretends fixture data came from a server.

A socket only counts as connected once the server's `ready` frame arrives. A bare
TCP upgrade is not enough: a proxy or a 404 page will happily accept a WebSocket
and then say nothing, and an app that treated that as "connected" would sit blank.

## Layout

```
src/
├── lib/
│   ├── ws.ts           # the /api/v2/ws client: request/reply, events, seq gaps, resume
│   ├── types.ts        # hand-written mirrors of app/schemas/* — the contract
│   ├── reportChat.ts   # offline answering: report passages matched, never written
│   ├── evidence.ts     # provenance kinds, coverage, stance/tier, quality arithmetic
│   ├── viewmodels.ts   # what screens read; both data sources produce these
│   └── format.ts       # numbers, clocks, dates, citations
├── state/store.tsx     # one store: connection, run, report, clusters, edits
├── data/               # the demo corpus and its run clock
├── components/         # Sidebar, Evidence primitives, SourcePanel, Lineage
└── screens/            # one file per screen in the sidebar
```

## Things worth knowing before changing it

- **Four provenance marks, not one link.** ¶ verified, ≈ approximate span,
  § abstract only, — not locatable. They mean different things about what was
  checked; collapsing them would misstate the evidence. `src/lib/evidence.ts`.
- **The source panel highlights by offset, never by search.** `claims.source`
  returns `highlight_start`/`highlight_end` relative to the paragraph it returns.
  Extraction normalises whitespace and case, so searching for the quote would miss
  or highlight the wrong span.
- **A gap in `seq` is reported, never interpolated.** The client detects it, tells
  the user which events were missed, and offers a reload. Reconnects resume with
  the last seq applied so the server replays only the gap.
- **Edits show the computed value beside yours.** The server pins an edited object
  with `user_edited` but keeps no per-change ledger, so the Edits screen records
  them as they are made. Nothing overwrites a computed value in the display.
- **Quality arithmetic is read from `quality_rationale`**, including the weights —
  so a change on the server shows up here rather than being contradicted by
  hard-coded numbers.
- **The print sheet is a layout, not a screenshot.** It matches what the backend's
  PDF export renders in Chromium.
- **Ask the report is grounded, and says when it is not.** The thread calls
  `chat.ask`, which answers from the report and its clusters only. An answer with
  `covered: false` is rendered as the loudest state on the screen, with the one
  remedy the chat does not have — `queries.followup`, a real run — attached to it.
  Citations are chips that open the cluster behind them, so provenance is a
  destination rather than a label.
- **A thread belongs to one report.** It is dropped whenever the active query
  changes: nothing on screen would say which report an old answer came from.
- **Offline, answers are matched, not written.** With no socket there is no model,
  so `reportChat.ts` quotes the report's own best-matching sentences and the turn
  is labelled as matched. The demo build never implies a model answered.
