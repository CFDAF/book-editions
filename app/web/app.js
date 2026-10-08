/* The reader's page for the new tree. Step 10 built the list, the three filters
 * and one row opened; Step 11 the header, the coverage ledger and the band.
 *
 * Three rules it is built around, and each of them is somebody else's decision
 * being obeyed rather than a choice made here:
 *
 * - **The browser stays dumb.** A version is a *complete* view and the page
 *   replaces what it holds; it never merges a delta (decision M). So `snapshot`
 *   below is assigned, never patched, and every count on screen is read out of
 *   it rather than accumulated.
 * - **A filter issues no request.** `filters.apply` runs over the snapshot in
 *   hand. `poll()` is the only thing in this file that fetches, apart from
 *   opening a row — which is a different gesture with a different cost, and it
 *   is the reader's.
 * - **Filters never touch identity** (rule 12). The header line is drawn from
 *   `snapshot.header`, which is computed unfiltered, so the original and the
 *   earliest edition found do not move when a filter does.
 *
 * Step 11 added the three things this page says about itself, and each one is a
 * rule rather than a design idea:
 *
 * - **The header states two facts and compares them.** The original where a
 *   source stated one, and the earliest edition found, always. Nothing is
 *   inferred from the pair, here or anywhere, and the rule that would infer it
 *   was measured wrong (A5).
 * - **The ledger counts what was found, never what exists** (decision C). A
 *   truncated query and a degraded source are drawn outside the fold, because
 *   rule 10 says every truncation is on the page and a reader who never opens
 *   the breakdown is still owed them.
 * - **The band is every record the gate refused** and nothing else — collapsed,
 *   never counted in a language group, each row labelled with the route that
 *   reached it and the score it was refused at (decision N).
 *
 * - **Printings fold behind the reader** (Step 12). S4 reads every SBN full
 *   record and publishes once, when it ends (decision AG); until then the
 *   envelope's `grouping` is true and the counts say they are provisional.
 * - **The duplicate hint is a mark, never a merge** (decision H): both rows of a
 *   pair carry it, with the reason, and a note under the list says how many
 *   pairs *may* be one edition. Only a shared ISBN merges, and that is
 *   `core.fold`'s, not the page's.
 *
 * - **Open Library's other records are offered, never merged in** (Step 13,
 *   decisions J and AI). The list is every record the title and author tests
 *   passed, collapsed and never capped; a row joins the language groups only
 *   when the reader adds it, labelled with the record it came from, and the
 *   header — what the catalogues tie to this work — does not move.
 *
 * - **An author with no title is a bibliography, not a list of editions**
 *   (Step 14, UC4, decision AJ). The person is chosen before anything is listed
 *   — the chooser is skipped only when one person answered every name form —
 *   and the rows are *works*. What the person edited, prefaced or is the subject
 *   of, and Open Library records that join no work, are two groups closed by
 *   default. A row is a title lookup waiting to happen: clicking it runs one.
 */

import { apply, emptyState, isEmpty, summary, UNKNOWN } from './filters.js';

const POLL_MS = 700;
const CHIPS_SHOWN = 8;          // before "more"; the rest are collapsed, not cut

const form = document.getElementById('search');
const results = document.getElementById('results');

let snapshot = null;            // the whole view, as the server last sent it
let job = null;                 // the envelope: stage, status, requests, failed
let jobId = null;
let generation = 0;             // which lookup is current; an old poll is dropped
let state = emptyState();
let openRows = new Map();       // edition id -> details, or 'loading', or an error
let showAllPublishers = false;
let showAllLanguages = false;
let showLedger = false;         // the breakdown; its warnings are never folded
let showBand = false;           // never open by default (decision N)
let showDuplicates = false;     // Open Library's other records, collapsed
let adding = new Set();         // record keys whose Add is in flight
let addError = null;            // an Add the server refused, in its own words
let picked = null;              // author mode: the ids ticked in the chooser
let showNamesakes = false;      // people whose records only mention the name
let showContributed = false;    // edited, prefaced, adapted, or about them
let showStrays = false;         // Open Library records that join no work
let showUnlinked = false;       // SBN records under the name that no work names
let readingRest = false;        // the read past the cap under the name is in flight
let pending = null;             // a work row's lookup: its title, author and spellings

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const joined = (parts) => parts.filter(Boolean).join('<span class="sep">·</span>');

// ---------------------------------------------------------------------------
// The transport
// ---------------------------------------------------------------------------

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const title = document.getElementById('title').value.trim();
  const author = document.getElementById('author').value.trim();
  const mine = ++generation;
  // The other spellings go only with the lookup a work row filled in; a title
  // the reader has since retyped is their own question.
  const variants = pending && pending.title === title && pending.author === author
    ? pending.variants : [];
  pending = null;

  snapshot = null; job = null; jobId = null;
  state = emptyState(); openRows = new Map();
  showAllPublishers = false; showAllLanguages = false;
  showLedger = false; showBand = false;
  showDuplicates = false; adding = new Set(); addError = null;
  picked = null; showNamesakes = false; showContributed = false; showStrays = false;
  showUnlinked = false; readingRest = false;
  render();

  let started;
  try {
    // The spelling switches go only when ticked: each costs requests (decision AV).
    const body = { title, author };
    if (variants.length) body.variants = variants;
    if (document.getElementById('title-spellings').checked) body.title_spellings = true;
    if (document.getElementById('author-spellings').checked) body.author_spellings = true;
    started = await post('/lookup', body);
  } catch (err) {
    if (mine === generation) { job = { error: String(err.message || err) }; render(); }
    return;
  }
  if (mine !== generation) return;
  jobId = started.id;
  poll(mine, 0);
});

async function post(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await answerOf(response);
  if (!response.ok && response.status !== 202) throw new Error(data.error || response.statusText);
  return data;
}

/* An answer that is not JSON (an HTML error page) is an error the page draws,
 * never one that ends the poll with the last state still on screen. */
async function answerOf(response) {
  try {
    return await response.json();
  } catch {
    const status = [response.status, response.statusText].filter(Boolean).join(' ');
    throw new Error(`the server answered ${status}, not JSON`);
  }
}

/* Poll until the job says it is done. Every answer is either a whole new
 * version or `{unchanged: true}` with the envelope, which is ~200 bytes — so
 * waiting costs almost nothing and the page can say what is happening while it
 * waits without inventing anything. */
async function poll(mine, held) {
  let response, data;
  try {
    response = await fetch(`/lookup/${jobId}?v=${held}`);
    data = await answerOf(response);
  } catch (err) {
    if (mine === generation) { job = { error: String(err.message || err) }; render(); }
    return;
  }
  if (mine !== generation) return;
  if (!response.ok) { job = { error: data.error || 'the lookup is gone' }; render(); return; }

  job = data.job || null;
  if (job?.done) readingRest = false;
  if (!data.unchanged) snapshot = data;
  render();
  // A job waiting for the reader to choose has nothing more to say until they do.
  if (!job || (!job.done && !job.choosing)) {
    setTimeout(() => poll(mine, snapshot ? snapshot.version : held), POLL_MS);
  }
}

// ---------------------------------------------------------------------------
// Opening one row
// ---------------------------------------------------------------------------

async function openRow(id) {
  openRows.set(id, 'loading');
  render();
  const mine = generation;
  try {
    const response = await fetch(`/lookup/${jobId}/edition/${encodeURIComponent(id)}`);
    const data = await answerOf(response);
    if (mine !== generation) return;
    openRows.set(id, response.ok ? data : { error: data.error || 'could not be opened' });
  } catch (err) {
    if (mine !== generation) return;
    openRows.set(id, { error: String(err.message || err) });
  }
  render();
}

// ---------------------------------------------------------------------------
// Adding Open Library's other records — the one gesture that changes the list
// ---------------------------------------------------------------------------

/* The server opens each record by key and publishes a new version before it
 * answers, so one poll fetches it. A record that failed to open comes back
 * marked on its own row, never as one that brought nothing (rule 5). */
async function addRecords(keys) {
  const mine = generation;
  keys.forEach((k) => adding.add(k));
  addError = null;
  render();
  try {
    await post(`/lookup/${jobId}/add`, { keys });
  } catch (err) {
    if (mine === generation) addError = String(err.message || err);
  }
  if (mine !== generation) return;
  keys.forEach((k) => adding.delete(k));
  poll(mine, snapshot ? snapshot.version : 0);
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

function render() {
  if (!snapshot && !job) { results.innerHTML = ''; return; }
  if (!snapshot) { results.innerHTML = waiting(); return; }
  if (snapshot.mode === 'author') { results.innerHTML = authorPage(); wireAuthor(); return; }
  if (snapshot.chooser) { results.innerHTML = titleChooser(); wireAuthor(); return; }

  const result = apply(snapshot, state);
  // No editions means no filters: a control over an empty list is furniture,
  // and what the reader needs there is the ledger and the band.
  pairs = pairsById();
  results.innerHTML = header() + ledger()
    + (snapshot.header.total_editions ? facets() : '') + summaryLine(result)
    + (result.groups.length ? result.groups.map(group).join('') : nothing())
    + duplicateNote() + footnote() + otherRecords() + band();
  wire();
}

function waiting() {
  if (job && job.error) return `<p class="nothing">${esc(job.error)}</p>`;
  const stage = job && job.stage ? job.stage : 'looking it up';
  return `<p class="waiting">${esc(stage)}<span class="dots">…</span></p>`;
}

/* The publication history: two statements, side by side, **never compared**.
 *
 * The first is the original, and only where a *source stated it* — a refused
 * work, a rejected Wikidata candidate or this tool's own inference all mean the
 * line is absent and the page says so, because uncertainty shows less (rule 8).
 * The second is the earliest edition found, always, labelled as what it is: a
 * statement about the catalogues, not about publishing history. No conclusion
 * is drawn from the pair, here or anywhere (decision D: the rule that would
 * have drawn it gave 8 false flags and 1 miss over 36 books).
 *
 * Every number here is read off `snapshot.header`, which is derived over the
 * whole store, so a filter change moves none of it (rule 12). */
function header() {
  const h = snapshot.header;
  const working = job && !job.done
    ? `<span class="still">${esc(job.stage)}<span class="dots">…</span></span>` : '';
  // The header states what the catalogues tie to this work, so a language the
  // reader's additions alone reach is not one of its languages (decision AI).
  const languages = (h.spans || []).filter((s) => s.editions).length;
  // No title at all means nothing was identified and nothing was listed. A
  // heading reading "No title recorded" is a placeholder where the honest
  // answer is the three lines under it, so it is left out rather than filled.
  return `<div class="overview">
    ${h.title ? `<h2>${esc(h.title)}</h2>` : ''}
    ${h.authors?.length ? `<p class="byline">${esc(h.authors.join('; '))}${h.author_adopted
      ? ` <span class="adopted">${esc(h.author_adopted.note)}</span>` : ''}</p>` : ''}
    ${originLine(h)}
    ${earliestLine(h)}
    <p class="found">${h.total_editions} ${job?.grouping ? (h.total_editions === 1 ? 'row' : 'rows')
      : (h.total_editions === 1 ? 'edition' : 'editions')}
       in ${languages} ${languages === 1 ? 'language' : 'languages'} ${working}</p>
    ${h.added ? `<p class="caveat added-note">and ${h.added} you added from Open Library's
       other records, listed with them and left out of the lines above</p>` : ''}
    ${job?.grouping ? `<p class="caveat provisional">counts are provisional until grouping
       ends: printings that share an ISBN become one edition</p>` : ''}
  </div>`;
}

function originLine(h) {
  if (h.original_stated && h.origin) {
    const by = h.original_stated_by
      ? `<span class="stated">stated by ${esc(h.original_stated_by)}</span>` : '';
    return `<p class="origin">${esc(capitalise(h.origin))} ${by}</p>`;
  }
  return `<p class="origin none">No source states when this work first appeared.</p>`;
}

/* The line is drawn whenever anything is dated, and it is drawn even when it
 * repeats the original's year: the two are different claims and the page is the
 * place that keeps them apart. */
function earliestLine(h) {
  const e = h.earliest;
  if (!e) return '';
  // The page's own name for an unrecorded language, so the tie line and the
  // chip that hides those rows call the same thing the same thing.
  const others = e.languages
    .map((code, i) => (code === UNKNOWN ? 'language not recorded' : e.language_names[i]))
    .filter((_, i) => e.languages[i] !== e.language);
  const imprint = joined([
    `<span class="year">${e.year}</span>`,
    e.language !== UNKNOWN ? esc(e.language_name) : '<em>language not recorded</em>',
    e.publisher ? esc(e.publisher) : null,
  ]);
  return `<p class="earliest"><span class="label">Earliest edition found</span>
    ${imprint}
    ${others.length ? `<span class="tie">also in ${esc(others.join(', '))}
      the same year</span>` : ''}
    <span class="caveat">what the catalogues hold${e.older_dropped
      ? `; ${e.older_dropped} ${e.older_dropped === 1 ? 'edition is' : 'editions are'}
         dated before the year stated above and left out` : ''}</span></p>`;
}

const capitalise = (text) => text.charAt(0).toUpperCase() + text.slice(1);

/* The coverage ledger: what this answer is made of.
 *
 * It **counts what was found and never states what exists** — there is no
 * census in this project and VIAF was measured as unusable for one (A6), so
 * decision C's *no census* half stands and decision N reversed only the other.
 *
 * One line, expandable, was the user's call on the ▣ sketch — **except** that a
 * truncation, a degraded source and a failed request are drawn outside the fold
 * whatever the triangle says. Rule 10 owes those to a reader who never opens
 * anything, and a note behind a disclosure triangle is a note nobody read. */
function ledger() {
  const l = snapshot.ledger;
  const warnings = [
    ...degraded(),
    ...(job?.incomplete ? [{ kind: 'red', text: job.incomplete }] : []),
    ...l.truncations.map((text) => ({ kind: 'red', text: `Read in part: ${text}.` })),
    // What a ticked switch asked is drawn outside the fold too: the reader
    // ticked it to learn exactly this.
    ...(l.spellings || []).map((text) => ({ kind: 'soft', text: `${capitalise(text)}.` })),
  ];
  return `<div class="ledger">
    <p class="ledger-head">
      <span class="total">${l.records.toLocaleString()}</span>
      ${l.records === 1 ? 'record' : 'records'} found for this work
      <button type="button" class="more-chips" data-ledger
              aria-expanded="${showLedger}">${showLedger ? 'fewer' : 'how'}</button>
    </p>
    ${showLedger ? ledgerBody(l) : ''}
    ${warnings.map((w) => `<p class="ledger-warn ${w.kind}">${esc(w.text)}</p>`).join('')}
  </div>`;
}

function ledgerBody(l) {
  const rows = l.lines.map((line) =>
    `<li><span class="n">${line.count.toLocaleString()}</span> ${esc(line.text)}</li>`);
  if (l.refused) {
    rows.push(`<li class="soft"><span class="n">${l.refused.toLocaleString()}</span>
      read and refused — listed under the editions</li>`);
  }
  if (l.editions !== l.admitted) {
    rows.push(`<li class="soft"><span class="n">${l.editions.toLocaleString()}</span>
      editions, once records sharing an ISBN are one row</li>`);
  }
  if (l.multi_language) {
    rows.push(`<li class="soft"><span class="n">${l.multi_language}</span>
      filed under two languages, counted once</li>`);
  }
  if (l.disbelieved) {
    rows.push(`<li class="soft"><span class="n">${l.disbelieved}</span>
      state a language this tool did not believe, and are grouped as unrecorded</li>`);
  }
  const notAsked = l.not_asked.map((why) => `<li class="soft">not asked: ${esc(why)}</li>`);
  // Timing is a technical note, not a warning: the user asked for it folded.
  if (job?.slow) notAsked.push(`<li class="soft">${esc(job.slow)}</li>`);
  return `<ul class="ledger-lines">${rows.join('')}${notAsked.join('')}</ul>`;
}

/* A source that lost requests, worded once on the server (`core.notes`). The
 * page never decides what "partial" means — it only draws it. */
function degraded() {
  const states = (job && job.sources) || {};
  return Object.keys(states).sort()
    .filter((name) => states[name] !== 'ok')
    .map((name) => ({ kind: 'red', text: `${name}: ${states[name]}` }));
}

/* Decision Z, said once under the list. The per-row label is not complete —
 * `VIA0214939` (a York Notes study guide) and `TO02081267` (the Meridiani
 * omnibus) are both headed by Orwell and carry nothing — so the list says what
 * it is rather than implying every non-edition is marked. */
function footnote() {
  const anySbn = snapshot.language_order.some((code) =>
    snapshot.editions_by_language[code].some((e) => e.sources.includes('SBN')));
  if (!anySbn) return '';
  return `<p class="footnote">SBN links study guides, graded readers, omnibus
    volumes and adaptations to a work. They are listed here as the catalogue
    files them, labelled where the catalogue's own fields say so.</p>`;
}

/* The loose-match band (decision N): every record the gate refused, collapsed,
 * opened deliberately, counted in no language group and in no total above.
 *
 * Two groups, and the split is the **route** rather than the score: a title
 * probe offered the record as one of this work's titles and the gate said no,
 * while the author sweep only ever said the same person is on it. 6,987 of
 * 8,833 refusals are the sweep's and 6,799 of those score exactly 0.0 **M**, so
 * calling them all "matched loosely" would be false. */
function band() {
  const b = snapshot.loose_matches;
  if (!b.total) return '';
  return `<div class="band">
    <button type="button" class="band-toggle" data-band aria-expanded="${showBand}">
      ${b.total.toLocaleString()} more ${b.total === 1 ? 'record was' : 'records were'}
      read and refused</button>
    ${showBand ? `<p class="caveat">Each row is scored against the titles this
       work is known by; the gate admits ${b.threshold} and above.</p>` : ''}
    ${showBand ? b.groups.map(bandGroup).join('') : ''}
  </div>`;
}

function bandGroup(g) {
  return `<section class="band-group">
    <p class="band-label">${g.count.toLocaleString()} ${esc(g.label)}</p>
    <ol class="band-rows">${g.rows.map(bandRow).join('')}</ol>
  </section>`;
}

function bandRow(r) {
  const imprint = joined([
    r.year ? esc(r.year) : null,
    r.publisher ? esc(r.publisher) : null,
    esc(r.route),
  ]);
  const title = r.url
    ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.id)}</a>`
    : esc(r.title || r.id);
  return `<li class="band-row">
    <span class="score">${(r.score ?? 0).toFixed(2)}</span>
    <span class="band-title">${title}</span>
    <span class="band-imprint">${imprint}</span>
  </li>`;
}

/* Both chip rows are the same gesture — narrow what is listed — so they get one
 * shape: a label, the options, and a chip that is on is blue and ruled. The
 * list is **collapsed, never truncated**: "more" shows every publisher there
 * is, however many, because a cap would be a claim about the data and would owe
 * rule 10 a note. */
function facets() {
  // The groups below are in publication-history order — the original first,
  // then the translations as they appeared — because that is the answer. A
  // chip row is a **control**, so it is ordered the way a control is useful:
  // most editions first, with the unrecorded language last whatever its size.
  // Both rows then share one rule, which is why they can share one shape.
  const spans = [...(snapshot.header.spans || [])].sort(
    (a, b) => (a.code === UNKNOWN) - (b.code === UNKNOWN)
      || (b.editions + (b.added || 0)) - (a.editions + (a.added || 0))
      || a.code.localeCompare(b.code));
  const langChips = spans.map((s) => chip(
    `data-lang="${esc(s.code)}"`, state.languages.includes(s.code),
    s.code === UNKNOWN ? 'language not recorded' : s.name, s.editions + (s.added || 0)));
  const pubs = snapshot.publishers || [];
  const pubChips = pubs.map((p) => chip(
    `data-pub="${esc(p.id)}"`, state.publishers.includes(p.id), p.label, p.editions));

  return `<div class="filters">
    ${chipRow('Language', langChips, showAllLanguages, 'lang')}
    ${pubs.length ? chipRow('Publisher', pubChips, showAllPublishers, 'pub') : ''}
    <p class="facets years">
      <span class="label">Years</span>
      <input type="text" id="year_from" inputmode="numeric" placeholder="from"
             value="${state.yearFrom ?? ''}" size="5">
      <span class="dash">–</span>
      <input type="text" id="year_to" inputmode="numeric" placeholder="to"
             value="${state.yearTo ?? ''}" size="5">
      ${isEmpty(state) ? '' : '<button type="button" class="clear" data-clear>clear all</button>'}
    </p>
  </div>`;
}

/* The toggle sits where it is needed rather than always in one place: `and N
 * more` reads as the tail of the list it continues, but `fewer` at the tail of
 * 390 expanded chips is a control you have to scroll past the whole list to
 * reach, so expanded it goes first. */
function chipRow(label, chips, expanded, kind) {
  const shown = expanded ? chips : chips.slice(0, CHIPS_SHOWN);
  const rest = chips.length - shown.length;
  const toggle = (text) =>
    `<button type="button" class="more-chips" data-more="${kind}">${text}</button>`;
  return `<p class="facets">
    <span class="label">${esc(label)}</span>
    ${expanded && chips.length > CHIPS_SHOWN ? toggle('fewer') : ''}
    ${shown.join('')}
    ${rest > 0 ? toggle(`and ${rest} more`) : ''}
  </p>`;
}

function chip(attrs, on, label, count) {
  return `<button type="button" class="chip" ${attrs} aria-pressed="${on}">${esc(label)}<span
    class="count">${count}</span></button>`;
}

/* The arithmetic the step's gate is about: every number here is read off the
 * unfiltered snapshot, and the reasons partition the hidden rows, so
 * `shown + hidden === total` and the breakdown sums to `hidden`. */
function summaryLine(result) {
  // With no filter on there is nothing to reconcile: the header two lines above
  // already says how many editions in how many languages, and repeating it as
  // "showing 943 of 943" is a sentence that exists only to be true.
  if (isEmpty(state)) return '';
  const warn = result.hidden ? ' warn' : '';
  return `<p class="facets-state${warn}" id="summary">${esc(summary(result))}</p>`;
}

/* Two different things the reader must not have to tell apart for themselves:
 * a filter that hides everything, and a question the catalogues answered with
 * nothing. The second is a real answer and says so — with the refused records
 * named, because "62 read and refused" is the whole of what was found and
 * pretending the lookup came back empty would be the opposite of this step. */
function nothing() {
  if (!isEmpty(state)) {
    return `<p class="nothing">Every edition is filtered out.
      <button type="button" data-clear>Clear the filters</button></p>`;
  }
  const refused = snapshot.loose_matches.total;
  return `<p class="nothing">No editions were found for this question.${refused
    ? ` ${refused.toLocaleString()} ${refused === 1 ? 'record was' : 'records were'}
        read and refused; they are listed below.` : ''}</p>`;
}

function group(g) {
  const shown = g.rows.length;
  const of = shown === g.editions ? '' : ` <span class="of">of ${g.editions}</span>`;
  const years = g.first_year
    ? (g.first_year === g.last_year ? `${g.first_year}` : `${g.first_year}–${g.last_year}`) : '';
  return `<section class="group">
    <div class="spine">
      <span class="code">${esc(g.code)}</span>
      <span class="name">${esc(g.name)}${g.is_original ? '<span class="tag">original</span>' : ''}</span>
      <span class="count">${shown}${of}</span>
      ${years ? `<span class="years">${esc(years)}</span>` : ''}
    </div>
    <ol class="editions">${g.rows.map(edition).join('')}</ol>
  </section>`;
}

/* `{edition id: [{other, why, missing}]}` off `snapshot.duplicate_hints`. A
 * pair always shares a language and a year, so both rows sit in one group. */
let pairs = new Map();

function pairsById() {
  const rows = new Map();
  for (const code of snapshot.language_order) {
    for (const e of snapshot.editions_by_language[code]) rows.set(e.id, e);
  }
  const out = new Map();
  for (const hint of snapshot.duplicate_hints || []) {
    const a = rows.get(hint.a);
    const b = rows.get(hint.b);
    if (!a || !b) continue;
    const missing = [a, b].filter((e) => !e.isbn).map((e) => e.sources.join(' · '));
    for (const [self, other] of [[a, b], [b, a]]) {
      if (!out.has(self.id)) out.set(self.id, []);
      out.get(self.id).push({ other, why: hint.why, missing });
    }
  }
  return out;
}

function duplicateTip(list) {
  return list.map(({ other, why, missing }) =>
    `possibly the same edition as the ${other.sources.join(' · ')} row `
    + `${other.publisher ? `(${other.publisher}, ${other.year})` : `(${other.year})`}: `
    + `${why}; ${missing.length === 2 ? 'neither record shows' : `the ${missing[0]} record shows no`} ISBN`)
    .join('\n');
}

/* The only aggregate statement about the hint, and it says *may*: hand-judged
 * it was right about 3 times in 4 before decision AX withheld pairs whose page
 * counts disagree (U5). Counted over the whole list, so a filter does not move
 * it (rule 12). */
function duplicateNote() {
  const n = (snapshot.duplicate_hints || []).length;
  if (!n) return '';
  return `<p class="footnote dup-note"><span class="dup-mark"></span>${n}
    ${n === 1 ? 'pair' : 'pairs'} in this list may be the same edition: same
    language, year and publisher, no page counts that disagree, and an ISBN
    missing on at least one side. They are listed separately and counted twice.</p>`;
}

/* Open Library's other records for this work (decision J), under the list.
 *
 * Every row the title and author tests passed, collapsed and never capped — a
 * cap would decide for the reader which one is an omnibus. Each row carries its
 * title, how many editions it holds and in which languages, because the list is
 * not clean: *Animal Farm / Nineteen Eighty-Four* passes both tests. */
function otherRecords() {
  const d = snapshot.duplicate_works;
  if (!d || !d.rows.length) return '';
  const open = d.rows.filter((r) => !r.added);
  const busy = open.filter((r) => adding.has(r.key)).length;
  const done = job?.done;
  const all = open.length > 1 && done
    ? `<button type="button" class="add-all" data-add-all ${busy ? 'disabled' : ''}>Add all
        ${open.length}</button>` : '';
  return `<div class="others">
    <button type="button" class="band-toggle" data-others aria-expanded="${showDuplicates}">
      Open Library holds ${d.rows.length} more ${d.rows.length === 1 ? 'record' : 'records'}
      under this author and title (${d.editions.toLocaleString()}
      ${d.editions === 1 ? 'edition' : 'editions'} between them)${d.added
        ? `, ${d.added} added` : ''}</button>
    ${showDuplicates ? `<p class="caveat">Adding one puts its editions into the language
       groups above, each marked with the record it came from. The header does not
       change: it states what the catalogues tie to this work.</p>
       ${addError ? `<p class="detail-row failed">${esc(addError)}</p>` : ''}
       ${all}
       <ol class="other-rows">${d.rows.map(otherRow).join('')}</ol>` : ''}
  </div>`;
}

function otherRow(r) {
  const facts = joined([
    `${r.editions.toLocaleString()} ${r.editions === 1 ? 'edition' : 'editions'}`,
    r.languages.length ? esc(r.languages.join(', ')) : null,
    r.year ? esc(r.year) : null,
  ]);
  let action;
  if (r.added) action = '<span class="added-tag">added</span>';
  else if (adding.has(r.key)) action = '<span class="soft">adding…</span>';
  else if (!job?.done) action = '';
  else action = `<button type="button" class="add" data-add="${esc(r.key)}">Add</button>`;
  return `<li class="other-row">
    <span class="band-title"><a href="https://openlibrary.org/works/${esc(r.key)}"
      target="_blank" rel="noopener">${esc(r.title || r.key)}</a></span>
    <span class="band-imprint">${facts}</span>
    ${r.failed ? `<span class="failed">Open Library did not answer; try again</span>` : ''}
    ${action}
  </li>`;
}

function otherTitle(key) {
  const row = (snapshot.duplicate_works?.rows || []).find((r) => r.key === key);
  return row ? row.title : key;
}

function printingsOf(e) {
  const p = e.printings || [];
  if (p.length < 2) return null;
  return `<span class="printings">${p.length} printings</span>`;
}

function edition(e) {
  const open = openRows.get(e.id);
  const dup = pairs.get(e.id);
  // First printing to latest: the header's earliest edition reads the first,
  // the list sorts on the latest (decision AG), and showing only the latest
  // made a 2014 edition reprinted in 2016 look like it did not exist.
  const shown = e.year && e.latest && e.year !== e.latest
    ? `${e.year}–${e.latest}` : e.latest || e.year;
  // A year not taken as the catalogue wrote it says so (decision AY): the
  // label is core's wording, the tooltip what the catalogue and SBN's index said.
  const note = e.year_note;
  const noted = note && note.note !== 'no date'
    ? `<span class="year-note${note.note === 'printed' ? ' printing' : ''}"
        title="${esc(note.detail)}">${esc(note.label)}</span>` : null;
  const imprint = joined([
    shown ? `<span class="year">${esc(shown)}</span>`
      : note?.shown ? `<span class="year unsure">${esc(note.shown)}</span>`
        : `<span class="year undated">${esc(note?.label || 'no year')}</span>`,
    noted,
    e.publisher ? `<span class="pub">${esc(e.publisher)}</span>` : null,
    e.isbn ? `<span class="isbn">${esc(e.isbn)}</span>` : null,
    printingsOf(e),
    e.medium && !/testo a stampa|^testo$/i.test(e.medium) ? `<em>${esc(e.medium)}</em>` : null,
    e.credited_to ? `<span class="credited">credited to ${esc(e.credited_to)}</span>` : null,
    // SBN returned this row on two language pages — a parallel text, a
    // Greek/Latin Odyssea. It is counted once, in one group, and the other code
    // is the catalogue's own statement rather than anything inferred here.
    e.also_in?.length
      ? `<span class="also">also filed as ${esc(e.also_in.map((l) => l.name).join(', '))}</span>`
      : null,
    e.added_from?.length
      ? `<span class="added">added from Open Library record ${esc(e.added_from
        .map((k) => `‘${otherTitle(k)}’`).join(', '))}</span>` : null,
  ]);
  return `<li class="edition${dup ? ' dup' : ''}"${dup ? ` title="${esc(duplicateTip(dup))}"` : ''}>
    <div class="edition-head">
      <span class="edition-title">${esc(e.title || 'no title recorded')}</span>
      <span class="badge">${esc(e.sources.join(' · '))}</span>
    </div>
    <p class="imprint">${imprint}</p>
    <button type="button" class="open" data-open="${esc(e.id)}"
            aria-expanded="${open ? 'true' : 'false'}">${open ? 'Close' : 'Details'}</button>
    ${open ? panel(e, open) : ''}
  </li>`;
}

/* An opened row. The three states are kept apart on purpose: what is still
 * being fetched, what a source refused to answer, and what a source answered
 * with nothing to add. A failed request must never look like an empty result
 * (`CLAUDE.md` rule 5), so the middle one says so in the reader's own words. */
function panel(e, data) {
  if (data === 'loading') return '<div class="more-body"><p class="detail-row">opening…</p></div>';
  if (data.error) {
    return `<div class="more-body"><p class="detail-row failed">${esc(data.error)}</p></div>`;
  }
  const ol = data.open_library;
  const rows = [];

  if (ol) {
    const physical = [ol.physical_format, ol.pages ? `${ol.pages} pages` : null,
      ol.pagination, ol.edition_name].filter(Boolean).join(' · ');
    if (physical) rows.push(detail('Description', esc(physical)));
    if (ol.by_statement) rows.push(detail('Statement of responsibility', esc(ol.by_statement)));
    if (ol.contributions?.length) rows.push(detail('Also credited', esc(ol.contributions.join('; '))));
    if (ol.places?.length) rows.push(detail('Published in', esc(ol.places.join('; '))));
    if (ol.series?.length) rows.push(detail('Series', esc(ol.series.join('; '))));
    if (ol.isbns?.length) rows.push(detail('ISBN', `<span class="isbn">${esc(ol.isbns.join(' '))}</span>`));
    if (ol.translation_of) rows.push(detail('Translation of', esc(ol.translation_of)));
    if (ol.archive_url) {
      rows.push(detail('Read it', `<span class="links"><a href="${esc(ol.archive_url)}"
        target="_blank" rel="noopener">Internet Archive</a></span>`));
    }
  } else if (data.evidence?.why_not) {
    // No label: a label announces a field, and this is the absence of one.
    rows.push(`<p class="detail-row soft">${esc(data.evidence.why_not)}</p>`);
  }

  rows.push(...sbnRows(data.sbn));

  if (data.buy_links?.length) {
    rows.push(detail('Find a copy', `<span class="links">${data.buy_links.map((b) =>
      `<a href="${esc(b.url)}" target="_blank" rel="noopener" class="${esc(b.kind)}">${esc(b.store)}</a>`)
      .join('')}</span>`));
  }
  const record = e.url
    ? `<span class="links"><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.sources[0])}</a></span>`
    : esc(e.sources.join(' · '));
  const routes = [...new Set((e.provenance || []).map((p) => p.route))].join(', ');
  rows.push(`<p class="detail-row provenance"><span class="label">Record</span>
    ${record} ${routes ? `· reached by the ${esc(routes)}` : ''}</p>`);

  const cover = ol?.cover_url
    ? `<img class="cover" src="${esc(ol.cover_url)}" alt="" loading="lazy">` : '';
  return `<div class="more-body">${cover}<div class="more-rows">${rows.join('')}</div></div>`;
}

/* SBN's half, read off the store by S4 — no request. `read` is how many of the
 * row's SBN records were read in full, so "held by no library" and "not read"
 * never look alike (`CLAUDE.md` rule 5's shape). Holdings are collapsed, never
 * cut: one record lists 851 libraries. */
function sbnRows(sbn) {
  if (!sbn) return [];
  if (!sbn.read) {
    const why = job?.grouping ? 'is still being read' : 'was not read';
    return [`<p class="detail-row soft">SBN's full record for this row ${why}, so its
      libraries are not listed here.</p>`];
  }
  const rows = [];
  if (sbn.physical) rows.push(detail('Physical', esc(sbn.physical)));
  if (sbn.series) rows.push(detail('Series', esc(sbn.series)));
  if (sbn.translators?.length) rows.push(detail('Translator', esc(sbn.translators.join('; '))));
  if (sbn.dewey) rows.push(detail('Dewey', esc(sbn.dewey)));
  const h = sbn.holdings || [];
  const place = (x) => esc([x.library, x.city].filter(Boolean).join(' · '));
  rows.push(h.length
    ? detail('Held by', h.length === 1 ? place(h[0])
      : `<details class="holdings"><summary>${place(h[0])} <span class="more-libs">and ${h.length - 1} more</span></summary>
         <ul>${h.slice(1).map((x) => `<li>${place(x)}</li>`).join('')}</ul></details>`)
    : detail('Held by', '<span class="soft">no library is recorded in SBN</span>'));
  return rows;
}

function detail(label, html) {
  return `<div class="detail-row"><span class="label">${esc(label)}</span>${html}</div>`;
}

// ---------------------------------------------------------------------------
// Events. Every one of these re-renders from the snapshot already in hand.
// ---------------------------------------------------------------------------

function wire() {
  results.querySelectorAll('[data-lang]').forEach((el) => {
    el.addEventListener('click', () => { state.languages = toggle(state.languages, el.dataset.lang); render(); });
  });
  results.querySelectorAll('[data-pub]').forEach((el) => {
    el.addEventListener('click', () => { state.publishers = toggle(state.publishers, el.dataset.pub); render(); });
  });
  results.querySelectorAll('[data-more]').forEach((el) => {
    el.addEventListener('click', () => {
      if (el.dataset.more === 'lang') showAllLanguages = !showAllLanguages;
      else showAllPublishers = !showAllPublishers;
      render();
    });
  });
  results.querySelectorAll('[data-ledger]').forEach((el) => {
    el.addEventListener('click', () => { showLedger = !showLedger; render(); });
  });
  results.querySelectorAll('[data-band]').forEach((el) => {
    el.addEventListener('click', () => { showBand = !showBand; render(); });
  });
  results.querySelectorAll('[data-others]').forEach((el) => {
    el.addEventListener('click', () => { showDuplicates = !showDuplicates; render(); });
  });
  results.querySelectorAll('[data-add]').forEach((el) => {
    el.addEventListener('click', () => addRecords([el.dataset.add]));
  });
  results.querySelectorAll('[data-add-all]').forEach((el) => {
    el.addEventListener('click', () => addRecords(
      snapshot.duplicate_works.rows.filter((r) => !r.added && !adding.has(r.key)).map((r) => r.key)));
  });
  results.querySelectorAll('[data-clear]').forEach((el) => {
    el.addEventListener('click', () => { state = emptyState(); render(); });
  });
  results.querySelectorAll('[data-open]').forEach((el) => {
    el.addEventListener('click', () => {
      const id = el.dataset.open;
      if (openRows.has(id)) { openRows.delete(id); render(); } else { openRow(id); }
    });
  });
  ['year_from', 'year_to'].forEach((id) => {
    const el = results.querySelector(`#${id}`);
    if (!el) return;
    el.addEventListener('change', () => {
      const value = el.value.trim();
      const parsed = /^\d{3,4}$/.test(value) ? Number(value) : null;
      if (id === 'year_from') state.yearFrom = parsed; else state.yearTo = parsed;
      render();
      const again = results.querySelector(`#${id}`);
      if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
    });
  });
}

function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

// ---------------------------------------------------------------------------
// Author mode (Step 14, UC4)
// ---------------------------------------------------------------------------

async function choose() {
  const mine = generation;
  const ids = [...(picked || [])];
  if (!ids.length) return;
  job = { ...job, choosing: false, stage: 'listing the works' };
  render();
  try {
    await post(`/lookup/${jobId}/choose`, { ids });
  } catch (err) {
    if (mine === generation) { addError = String(err.message || err); render(); }
    return;
  }
  if (mine === generation) poll(mine, snapshot ? snapshot.version : 0);
}

/* A work row is the title lookup for that work (UC3): the same form, filled in
 * and submitted, so what the reader gets is exactly what typing it would give. */
function lookUp(title, author, variants) {
  pending = { title, author, variants };
  document.getElementById('title').value = title;
  document.getElementById('author').value = author;
  form.requestSubmit();
}

function authorPage() {
  if (job?.choosing) return chooser();
  if (!snapshot.works) return waiting();
  const name = (snapshot.people.find((p) => p.id === snapshot.chosen[0]) || {}).name
    || snapshot.asked;
  const works = snapshot.works;
  const cut = snapshot.truncations || [];
  return `<div class="overview">
      <h2>${esc(name)}</h2>
      <p class="found">${works.length} ${works.length === 1 ? 'work' : 'works'},
        newest first${job && !job.done ? ` <span class="still">${esc(job.stage)}<span
        class="dots">…</span></span>` : ''}</p>
      ${cut.map((line) => `<p class="caveat">${esc(line)}</p>`).join('')}
      ${readRest()}
      ${degraded().map((d) => `<p class="caveat failed">${esc(d.text)}</p>`).join('')}
    </div>
    <ol class="works">${works.map(workRow).join('')}</ol>
    ${collapsed('contributed', showContributed, snapshot.contributed,
      (n) => `${n} more under this name: written with others, edited, prefaced, adapted or about them`,
      workRow)}
    ${collapsed('unlinked', showUnlinked, snapshot.unlinked,
      (n) => `${n} more ${n === 1 ? 'title' : 'titles'} SBN files under this name and under no work`,
      unlinkedRow)}
    ${collapsed('strays', showStrays, snapshot.band,
      (n) => `${n} Open Library ${n === 1 ? 'record matches' : 'records match'} no work above`,
      strayRow)}`;
}

/* A bare title that names several books (decision AN): the books and nothing
 * else. Without an author SBN's work authority cannot be asked, so a list here
 * would be Open Library's alone and would describe several books at once. A
 * pick is the title lookup again, with that book's author. */
function titleChooser() {
  const c = snapshot.chooser;
  return `<div class="overview chooser">
      <h2>${esc(c.heading)}</h2>
      <p class="found">no author was typed, and the catalogues name more than one</p>
      ${degraded().map((d) => `<p class="caveat failed">${esc(d.text)}</p>`).join('')}
      <ol class="works">${c.books.map((b) => bookRow(c.title, b)).join('')}</ol>
    </div>`;
}

function bookRow(title, b) {
  const facts = joined([
    b.first_year ? esc(b.first_year) : null,
    `${b.editions} ${b.editions === 1 ? 'record' : 'records'}`,
    esc(b.sources.join(', ')),
  ]);
  return `<li class="work"><button type="button" class="work-open"
      data-work="${esc(title)}" data-by="${esc(b.authors[0] || '')}" data-variants="[]">
      <span class="work-title">${esc(b.title)}</span>
      <span class="person-name">${esc(b.authors.join('; '))}</span></button>
      <span class="band-imprint">${facts}</span></li>`;
}

/* Decision BA: the records past the cap under the name, read on demand, under
 * the truncation line it answers. Only the group filed under no work moves;
 * the line stands until the read is done. */
function readRest() {
  const u = snapshot.unread;
  const refused = addError ? `<p class="detail-row failed">${esc(addError)}</p>` : '';
  if (!u) return refused;
  const busy = readingRest || !job?.done;
  const records = `${u.records.toLocaleString()} ${u.records === 1 ? 'record' : 'records'}`;
  return `<p class="read-rest"><button type="button" class="add-all" data-read-rest
      ${busy ? 'disabled' : ''}>${readingRest ? `Reading the other ${records}…`
        : `Read the other ${records} under this name`}</button>
      <span class="band-imprint">${u.pages.toLocaleString()} more SBN
        ${u.pages === 1 ? 'page' : 'pages'}</span></p>${refused}`;
}

async function readTheRest() {
  const mine = generation;
  readingRest = true;
  addError = null;
  render();
  try {
    await post(`/lookup/${jobId}/more`, {});
  } catch (err) {
    if (mine === generation) { readingRest = false; addError = String(err.message || err); render(); }
    return;
  }
  if (mine === generation) poll(mine, snapshot ? snapshot.version : 0);
}

function unlinkedRow(u) {
  // Years settled as an edition row's are (decision AY), labelled the same way.
  const note = u.year_note;
  const years = u.first_year
    ? esc(u.last_year && u.last_year !== u.first_year ? `${u.first_year}–${u.last_year}` : `${u.first_year}`)
    : note?.shown ? `<span class="year unsure">${esc(note.shown)}</span>`
      : 'no year recorded';
  const facts = joined([
    years,
    note && note.note !== 'no date'
      ? `<span class="year-note${note.note === 'printed' ? ' printing' : ''}"
          title="${esc(note.detail)}">${esc(note.label)}</span>` : null,
    `${u.records.length} ${u.records.length === 1 ? 'record' : 'records'}`,
    u.credited_to?.length ? `credited to ${esc(u.credited_to.join('; '))}` : null,
  ]);
  const author = (snapshot.people.find((p) => p.id === snapshot.chosen[0]) || {}).name || '';
  return `<li class="work"><button type="button" class="work-open"
      data-work="${esc(u.title)}" data-by="${esc(author)}" data-variants="[]">
      <span class="work-title">${esc(u.title)}</span></button>
      <span class="band-imprint">${facts}</span></li>`;
}

function chooser() {
  if (picked === null) picked = new Set(snapshot.resolved ? [snapshot.resolved] : []);
  const people = snapshot.people;
  const named = people.filter((p) => p.agrees);
  const others = people.filter((p) => !p.agrees);
  const also = (snapshot.forms || []).slice(1);
  if (!people.length) {
    return `<p class="nothing">SBN's name authority has nobody under
      ${esc(snapshot.asked)}.</p>`;
  }
  return `<div class="overview chooser">
      <h2>Who do you mean?</h2>
      <p class="found">SBN's name authority · ${named.length}
        ${named.length === 1 ? 'person' : 'people'} by this name</p>
      ${also.length ? `<p class="caveat">Also asked as ${esc(also.join(', '))}
        (Wikidata's names for this person)</p>` : ''}
      <ol class="people">${named.map(personRow).join('')}</ol>
      ${others.length ? `<button type="button" class="band-toggle" data-namesakes
          aria-expanded="${showNamesakes}">${others.length} more whose records mention
          this name</button>
        ${showNamesakes ? `<ol class="people">${others.map(personRow).join('')}</ol>` : ''}`
        : ''}
      ${addError ? `<p class="detail-row failed">${esc(addError)}</p>` : ''}
      <button type="button" class="list-works" data-choose
        ${picked.size ? '' : 'disabled'}>List works</button>
    </div>`;
}

function personRow(p) {
  const facts = joined([
    p.records != null ? `${p.records.toLocaleString()} ${p.records === 1 ? 'record' : 'records'}` : null,
    p.languages ? `${p.languages} ${p.languages === 1 ? 'language' : 'languages'}` : null,
  ]);
  return `<li class="person"><label>
      <input type="checkbox" data-person="${esc(p.id)}" ${picked.has(p.id) ? 'checked' : ''}>
      <span class="person-name">${esc(p.heading.replace(/\s+,\s*/g, ', '))}</span>
      <span class="band-imprint">${facts}</span></label></li>`;
}

function workRow(w) {
  const year = w.year
    ? (w.year_kind === 'original' ? `${w.year}` : `earliest edition found ${w.year}`)
    : 'no year recorded';
  const facts = joined([
    esc(year),
    w.languages.length ? `${w.languages.length} ${w.languages.length === 1 ? 'language'
      : 'languages'}` : null,
    w.medium ? esc(w.medium) : null,
    w.unanswered ? '<span class="failed">SBN did not answer for this work; whose it is is unchecked</span>' : null,
    snapshot.works.includes(w) ? null
      : w.statement ? esc(w.statement)
        : w.credited_to?.length ? `credited to ${esc(w.credited_to.join('; '))}` : null,
  ]);
  return `<li class="work"><button type="button" class="work-open"
      data-work="${esc(w.lookup.title)}" data-by="${esc(w.lookup.author)}"
      data-variants="${esc(JSON.stringify(w.lookup.variants || []))}">
      <span class="work-title">${esc(w.title)}</span></button>
      <span class="band-imprint">${facts}</span>${derivedRows(w.derived)}</li>`;
}

/* Decision BC: what was made from the book, under it and never in its place. */
function derivedRows(derived) {
  if (!derived?.length) return '';
  return `<ol class="derived">${derived.map((d) => `<li><span class="derived-title">↳
      ${esc(d.title)}</span> <span class="band-imprint">${joined([
      `${esc(d.medium)}${d.year ? ` ${esc(d.year)}` : ''}`,
      `${d.records} ${d.records === 1 ? 'record' : 'records'}`])}</span></li>`).join('')}</ol>`;
}

function strayRow(d) {
  const facts = joined([
    d.editions ? `${d.editions} ${d.editions === 1 ? 'edition' : 'editions'}` : null,
    d.languages.length ? esc(d.languages.join(', ')) : null,
    d.year ? esc(d.year) : null,
  ]);
  return `<li class="other-row"><span class="band-title"><a
      href="https://openlibrary.org/works/${esc(d.key)}" target="_blank" rel="noopener">${esc(d.title
      || d.key)}</a></span><span class="band-imprint">${facts}</span></li>`;
}

function collapsed(name, open, list, label, row) {
  if (!list || !list.length) return '';
  return `<div class="band">
      <button type="button" class="band-toggle" data-fold="${name}"
        aria-expanded="${open}">${label(list.length)}</button>
      ${open ? `<ol class="works">${list.map(row).join('')}</ol>` : ''}</div>`;
}

function wireAuthor() {
  results.querySelectorAll('[data-person]').forEach((el) => {
    el.addEventListener('change', () => {
      if (el.checked) picked.add(el.dataset.person); else picked.delete(el.dataset.person);
      render();
    });
  });
  results.querySelectorAll('[data-namesakes]').forEach((el) => {
    el.addEventListener('click', () => { showNamesakes = !showNamesakes; render(); });
  });
  results.querySelectorAll('[data-choose]').forEach((el) => el.addEventListener('click', choose));
  results.querySelectorAll('[data-read-rest]').forEach((el) => el.addEventListener('click', readTheRest));
  results.querySelectorAll('[data-fold]').forEach((el) => {
    el.addEventListener('click', () => {
      if (el.dataset.fold === 'contributed') showContributed = !showContributed;
      else if (el.dataset.fold === 'unlinked') showUnlinked = !showUnlinked;
      else showStrays = !showStrays;
      render();
    });
  });
  results.querySelectorAll('[data-work]').forEach((el) => {
    el.addEventListener('click', () => lookUp(el.dataset.work, el.dataset.by,
      JSON.parse(el.dataset.variants || '[]')));
  });
}
