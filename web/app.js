/* Book editions — UI logic.

   Nothing clever: one fetch, one render. The only state worth holding is the
   last report (so facet filtering can re-render without another lookup) and
   which facets are active. */

const form = document.getElementById('search');
const results = document.getElementById('results');
const sourcesLine = document.getElementById('sources');
const submit = document.getElementById('submit');
const filtersToggle = document.getElementById('toggle-filters');
const filters = document.getElementById('filters');

let report = null;
let activeFacets = new Set();
let holdingsLink = '';
let chosen = '';           // selected work when several share the title

const text = (s) => (s == null ? '' : String(s));
// A title attribute keeps every newline and every space of indentation it is
// given, so anything written across lines has to be flattened first.
const tip = (label, explain) =>
  `<span title="${esc(String(explain).replace(/\s+/g, ' ').trim())}">${esc(label)}</span>`;
const esc = (s) => text(s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ------------------------------------------------------------------ helpers */

function joined(parts, className = 'sep') {
  return parts.filter(Boolean).join(`<span class="${className}">&middot;</span>`);
}

// SBN inverts names and appends life dates; Open Library does neither.
function authorName(raw) {
  const name = String(raw || '').replace(/\s*<[^>]*>/g, '').trim().replace(/,$/, '');
  const parts = name.split(',');
  if (parts.length === 2 && parts[1].trim()) return `${parts[1].trim()} ${parts[0].trim()}`;
  return name;
}

function year(e) {
  // Open Library dates arrive in every shape going ('June 1985', '1972-01-01').
  const m = text(e.year).match(/\b(1[0-9]{3}|20[0-9]{2})\b/);
  return m ? m[1] : text(e.year);
}

/* ------------------------------------------------------------------- render */

// Everything above the list describes one work. When several books share a
// title the pipeline resolves exactly one of them — the one Wikidata and Open
// Library agreed on — and the overview is about that one. Pick a different
// book from the chooser and its author, its first-publication claim and its
// "original" marker all still belong to somebody else's book. So: is the book
// the reader picked the one the catalogues resolved?
const fold = (s) => String(s || '').toLowerCase().replace(/[^a-z\u00c0-\u024f ]/g, '').trim();

function isResolvedWork(r, choice) {
  if (!choice) return true;                       // nothing chosen: the overview is itself
  const known = (r.cluster?.author_names || []).map(fold).filter(Boolean);
  if (!known.length) return false;                // no cluster to belong to
  return choice.authors.some((a) => known.includes(fold(a)));
}

// A first-publication date is a claim about a work, not about a title string.
// Anyone else who happens to share the title gets the honest, weaker statement
// the catalogue can actually support: the earliest edition of theirs we found.
// Every other case is phrased by the pipeline, in `overview.origin`, so this
// and the CLI cannot say it two different ways.
function originPhrase(o, choice, mine) {
  if (choice && !mine) {
    return choice.first_year ? `earliest edition found ${esc(choice.first_year)}` : null;
  }
  return esc(o.origin) || null;
}

// The header is a publication history, not a verdict: when the work first
// appeared, in which language, and when each translation followed. That is what
// a list of editions actually tells you.
function renderOverview(r) {
  const o = r.overview || {};
  if (!o.found) {
    return `<section class="overview" data-empty="true">
      <h2>${esc(o.title || r.query_title || 'Nothing found')}</h2>
      <p class="byline">No editions found. Checked
        ${esc(Object.entries(r.sources || {}).filter(([, v]) => v === 'ok')
          .map(([n]) => n).join(', ') || 'no sources')}.</p>
    </section>`;
  }

  const choice = chosen ? (r.choices || []).find((c) => c.key === chosen) : null;
  const mine = isResolvedWork(r, choice);
  const spans = chosen ? spansFor(r, chosen, mine) : (o.spans || []);

  // With several books sharing the title and none picked, the list below is an
  // aggregate — naming one of the four authors over it claims the whole thing
  // is theirs. The chooser directly underneath already names all of them.
  const authors = choice ? choice.authors : (o.ambiguous ? [] : (o.authors || []));
  const total = spans.reduce((n, s) => n + s.editions, 0);

  const byline = [
    esc(authors.join('; ')) || null,
    originPhrase(o, choice, mine),
    `${total} edition${total === 1 ? '' : 's'} in
      ${spans.length} language${spans.length === 1 ? '' : 's'}`,
  ].filter(Boolean).join(' · ');

  const years = spans.flatMap((s) => [s.first_year, s.last_year]).filter(Boolean);
  const lo = Math.min(...years, o.original_year || Infinity);
  const hi = Math.max(...years, o.original_year || -Infinity);
  const range = Math.max(hi - lo, 1);

  const rows = spans.map((s) => {
    // A bar on a shared time axis shows at a glance how long after the original
    // a translation arrived — the thing a list of years makes you work out.
    let bar = '<span class="bar-none">no dates recorded</span>';
    if (s.first_year) {
      const left = ((s.first_year - lo) / range) * 100;
      const width = Math.max(((s.last_year - s.first_year) / range) * 100, 1.2);
      bar = `<span class="bar" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></span>`;
    }
    const span = s.first_year
      ? (s.last_year && s.last_year !== s.first_year
          ? `${s.first_year}\u2013${s.last_year}` : String(s.first_year))
      : '\u2014';
    return `<li${s.is_original ? ' class="is-original"' : ''}>
      <span class="span-lang">${esc(s.name)}${s.is_original
        ? ' <span class="tag">original</span>' : ''}</span>
      <span class="span-track">${bar}</span>
      <span class="span-years">${esc(span)}</span>
      <span class="span-count">${s.editions}</span>
    </li>`;
  }).join('');

  // An inferred original is a weaker claim than a catalogued one; say so.
  const caveat = o.original_inferred && mine
    ? `<p class="inferred">Original identified by inference, not by a catalogue
        record${o.original_basis ? ` — ${esc(o.original_basis)}` : ''}.</p>`
    : '';

  return `<section class="overview">
    <h2>${esc(o.title)}</h2>
    <p class="byline">${byline}</p>
    ${caveat}
    <ul class="spans">${rows}</ul>
  </section>`;
}

// Recompute the spans for one chosen book, so the header describes what is shown.
function spansFor(r, group, mine) {
  const out = [];
  for (const [code, editions] of Object.entries(r.editions_by_language || {})) {
    const mine = editions.filter((e) => e.work_group === group);
    if (!mine.length) continue;
    const years = mine.map((e) => parseInt(year(e), 10)).filter((y) => !Number.isNaN(y));
    out.push({
      code,
      name: r.language_names?.[code] || code,
      editions: mine.length,
      first_year: years.length ? Math.min(...years) : null,
      last_year: years.length ? Math.max(...years) : null,
      is_original: mine && code === r.overview?.original_language,
    });
  }
  out.sort((a, b) => (a.first_year || 9999) - (b.first_year || 9999));
  return out;
}

// A widely held book can sit in 229 libraries. Printing all of them turns the
// page into the wall of data this design exists to avoid, so the list is capped
// and the remainder counted — the question being answered is "is there one near
// me", which the first screenful of cities answers.
const HOLDINGS_SHOWN = 14;

function renderHoldings(holdings) {
  const byCity = new Map();
  holdings.forEach((h) => {
    const city = h.city || 'Location not recorded';
    if (!byCity.has(city)) byCity.set(city, []);
    byCity.get(city).push(h.library);
  });
  const cities = [...byCity.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const items = cities.slice(0, HOLDINGS_SHOWN)
    .map(([city, libs]) => `<li><span class="city">${esc(city)}</span>
      <span class="library">${esc(libs.filter(Boolean).join('; '))}</span></li>`).join('');
  const rest = cities.length - HOLDINGS_SHOWN;
  const label = `Held by ${holdings.length} ${holdings.length === 1 ? 'library' : 'libraries'}`
    + ` in ${cities.length} ${cities.length === 1 ? 'place' : 'places'}`;
  return `<p class="detail-row"><span class="label">${esc(label)}</span></p>
    <ul class="holdings">${items}</ul>
    ${rest > 0 ? `<p class="holdings-more">and ${rest} more, listed on the
       <a href="${esc(holdingsLink)}" target="_blank" rel="noopener">SBN record</a></p>` : ''}`;
}

function renderEdition(e) {
  // 'original' is assigned only where an edition sits in the original language
  // *and* carries the work's first-publication year — a handful of rows at
  // most, and the ones worth pointing at. 'translation' is true of every row
  // in a translated group, so it stays grey: a mark every sibling also carries
  // marks nothing.
  const role = e.role !== 'reprint'
    ? `<span class="role" data-role="${esc(e.role)}">${esc(e.role)}</span>` : '';
  const others = (e.available_languages || [])
    .filter((c) => c !== e.language)
    .map((c) => report?.language_names?.[c] || c);
  // Year first, then publisher. Within one work every row repeats the same
  // title and the same author, so leading with either buries the two fields
  // that actually tell two editions apart — and the list is already sorted by
  // year, which a year in third position hides.
  const imprint = joined([
    year(e) ? `<span class="year">${esc(year(e))}</span>` : null,
    e.publisher ? `<span class="pub">${esc(e.publisher)}</span>` : null,
    e.authors?.length ? `<span class="by">${esc(e.authors.map(authorName).join('; '))}</span>` : null,
    e.series ? esc(e.series) : null,
    e.isbn ? `<span class="isbn">${esc(e.isbn)}</span>` : null,
    e.edition_count ? `${e.edition_count} edition${e.edition_count === 1 ? '' : 's'}` : null,
    e.medium && !/testo a stampa/i.test(e.medium) ? `<em>${esc(e.medium)}</em>` : null,
    others.length ? `also in ${esc(others.join(', '))}` : null,
  ]);

  const evidence = (e.evidence || []).length
    ? `<ul class="evidence">${e.evidence.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`
    : '';

  const rows = [];
  if (e.physical) rows.push(`<p class="detail-row"><span class="label">Description</span>${esc(e.physical)}</p>`);
  if (e.translators?.length) {
    rows.push(`<p class="detail-row"><span class="label">Translator</span>${esc(e.translators.join('; '))}</p>`);
  }
  if (e.holdings?.length) { holdingsLink = e.url || ''; rows.push(renderHoldings(e.holdings)); }
  if (e.buy_links?.length) {
    const links = e.buy_links.map((b) =>
      `<a href="${esc(b.url)}" target="_blank" rel="noopener" class="${esc(b.kind)}">${esc(b.store)}</a>`).join('');
    rows.push(`<p class="detail-row"><span class="label">Search for a copy</span>
      <span class="links">${links}</span></p>`);
  }
  const refs = [
    e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${e.sbn_bid ? 'SBN record' : 'Open Library'}</a>` : null,
  ].filter(Boolean).join('');
  rows.push(`<p class="detail-row provenance"><span class="label">Record</span>
    <span class="links">${refs}</span> ${esc(e.source)}
    ${e.match_reasons?.length ? `&middot; matched by ${esc(e.match_reasons.join(', '))}` : ''}</p>`);

  // Two different codes sit here and neither explains itself, so each carries
  // its own tooltip rather than being joined into one opaque string.
  const shelf = [
    e.dewey ? tip(e.dewey, `Dewey class ${e.dewey} — the subject number this edition
      is shelved under. Being a number rather than words, it is the same in every
      language, which is how an Italian edition gets matched to its original.`) : null,
    e.sbn_bid ? tip(e.sbn_bid, `SBN ${e.sbn_bid} — this record's permanent number in
      the Italian national union catalogue, the one the libraries themselves use.`) : null,
  ].filter(Boolean).join('  ');

  return `<li class="edition" tabindex="-1">
    <div class="edition-head">
      <span class="edition-title">${role}${esc(e.title)}</span>
      ${shelf ? `<span class="shelfmark">${shelf}</span>` : ''}
    </div>
    ${imprint ? `<p class="imprint">${imprint}</p>` : ''}
    ${evidence}
    <details class="more"><summary>Details</summary>
      <div class="more-body">${rows.join('')}</div>
    </details>
  </li>`;
}

// Both filters on this page are the same gesture — narrow what is listed —
// so they get one shape: a label, options separated by slashes, and a line
// underneath saying in words what is on. An option that is on is blue and
// double-ruled. Nothing is ticked; a tick on top of that says the same thing
// twice, and three controls each ticking differently said it three ways.
function filterRow(label, options, state) {
  const items = options.map((o) => `<button type="button" ${o.attrs}
    aria-pressed="${o.on}">${o.label}${o.meta || ''}</button>`)
    .join('<span class="sep">/</span>');
  return `<p class="facets"><span class="label">${esc(label)}</span> ${items}</p>`
    + (state ? `<p class="facets-state${state.warn ? ' warn' : ''}">${state.html}</p>` : '');
}

const count = (v) => `<span class="count">${esc(v)}</span>`;

// Titles are not unique. Rather than silently blending two different books
// into one answer, offer the choice on author and year.
function chooser(r) {
  if (!(r.choices || []).length) return '';
  const who = (c) => (c.authors.length ? c.authors.join('; ') : 'author not recorded');
  const options = r.choices.map((c) => {
    const span = c.first_year && c.last_year && c.first_year !== c.last_year
      ? `${c.first_year}\u2013${c.last_year}` : (c.last_year || 'year unknown');
    return {
      attrs: `data-choice="${esc(c.key)}"`,
      on: chosen === c.key,
      label: esc(who(c)),
      // Two bare numbers side by side read as one; the years are the span, the
      // second number is how many editions fall inside it.
      meta: ` ${count(span)}<span class="sep">&middot;</span>${count(c.editions)}`,
    };
  });
  options.push({ attrs: 'data-choice=""', on: chosen === '', label: 'All of them' });

  const picked = r.choices.find((c) => c.key === chosen);
  const state = picked
    ? { html: `Showing ${esc(who(picked))} only.
        <button type="button" class="clear-choice">Show all ${r.choices.length}</button>` }
    : { warn: true, html: `${r.choices.length} different books share this title —
        everything below mixes all of them together.` };
  return filterRow('Which book', options, state);
}

function andList(names) {
  if (names.length < 2) return names[0] || '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

// The counts here count what is listed below and nothing else. They used to be
// SBN's own facet counts, which come from a sweep of the *author's* whole
// catalogue: "francese 124" could sit above a single Italian edition and meant
// "SBN holds 124 French records by this author" — an answer to a question
// nobody asked. Languages with no editions were greyed out, which exposed the
// mismatch without ever explaining it, and offered nothing to click.
//
// The filters are a union, not a narrowing: several can be on at once and each
// one adds a language back. That has to be legible at a glance, so an active
// filter is set in blue and double-ruled, and a line underneath says in words
// what is showing and what that is hiding.
function languageFilter(r, groups) {
  if (groups.length < 2 && !activeFacets.size) return '';
  const name = (code) => r.language_names?.[code] || code;

  const options = groups.map(([code, editions]) => ({
    attrs: `data-facet="${esc(code)}"`,
    on: activeFacets.has(code),
    label: esc(name(code)),
    meta: ` ${count(editions.length)}`,
  }));

  const on = groups.filter(([code]) => activeFacets.has(code));
  let state = null;
  if (on.length) {
    const off = groups.filter(([code]) => !activeFacets.has(code));
    const hidden = off.reduce((n, [, editions]) => n + editions.length, 0);
    state = { html: `Showing ${esc(andList(on.map(([c]) => name(c))))}.
      ${hidden ? `${hidden} edition${hidden === 1 ? '' : 's'} in
        ${off.length} other language${off.length === 1 ? '' : 's'} hidden.` : ''}
      <button type="button" class="clear-facets">Show all</button>` };
  }
  return filterRow('Languages', options, state);
}

function render() {
  const r = report;
  // The chosen work is applied first and the language counts are taken after
  // it: picking one of several books sharing a title changes how many editions
  // each language holds, and a count that disagrees with the list under it is
  // worse than no count.
  const groups = Object.entries(r.editions_by_language || {})
    .map(([code, editions]) => [code, chosen
      ? editions.filter((e) => e.work_group === chosen) : editions])
    .filter(([, editions]) => editions.length);

  const shown = activeFacets.size
    ? groups.filter(([code]) => activeFacets.has(code)) : groups;
  const body = shown.map(([code, editions]) => `<section class="group">
      <div class="group-body">
        <div class="spine">
          <span class="code">${code === 'unknown' ? '&mdash;' : esc(code)}</span>
          <span class="name">${esc(r.language_names?.[code] || '')}</span>
          <span class="count">${editions.length}</span>
        </div>
        <ul class="editions">${editions.map(renderEdition).join('')}</ul>
      </div>
    </section>`).join('');

  const notes = (r.notes || [])
    .filter((n) => !n.startsWith('Incomplete:') && !/different books share this title/.test(n))
    .concat((r.errors || []).map((e) => `!${e}`));
  if (r.filters_applied) {
    notes.unshift(`Filtered to ${r.filters_applied} — editions outside that, and any `
      + 'with no recorded year, are not listed.');
  }
  const notesHtml = notes.length
    ? `<ul class="notes">${notes.map((n) => n.startsWith('!')
        ? `<li class="warn">${esc(n.slice(1))}</li>` : `<li>${esc(n)}</li>`).join('')}</ul>`
    : '';

  // A partial answer must not be mistakable for a complete one: a dropped
  // request can remove an entire language, which looks exactly like that
  // language simply having no editions.
  const partial = Object.entries(r.sources || {})
    .filter(([, state]) => String(state).startsWith('partial'));
  const warning = partial.length
    ? `<p class="incomplete"><strong>Some editions are probably missing.</strong>
        ${partial.map(([n, s]) => `${esc(n)} — ${esc(s.replace('partial ', ''))}`).join('; ')}.
        Whatever arrived is cached, so searching again is quick and usually fills the gaps.
        <button type="button" id="retry">Search again</button></p>`
    : '';

  // A filter that hides everything should say so, not render a blank page.
  // A language filter can survive a change of chosen work and leave nothing to
  // show — and then nothing in the filter row is ticked either, because the
  // language is no longer among the work's. Name it here or the empty page has
  // no visible cause.
  const empty = activeFacets.size && !body
    ? `<p class="nothing">Nothing in
         ${esc(andList([...activeFacets].map((c) => r.language_names?.[c] || c)))}
         for this book. <button type="button" class="clear-facets">Show all
         languages</button></p>`
    : '';
  results.innerHTML = renderOverview(r) + warning + chooser(r)
    + languageFilter(r, groups) + body + empty + notesHtml;
  renderSources(r.sources);
  wire();
}

function renderSources(sources) {
  sourcesLine.innerHTML = Object.entries(sources || {}).map(([name, state]) => {
    const cls = state === 'ok' ? '' : ' class="down"';
    return `<span${cls}>${esc(name)} ${esc(state)}</span>`;
  }).join(' &middot; ');
}

/* -------------------------------------------------------------- interaction */

function wire() {
  const retry = document.getElementById('retry');
  if (retry) retry.addEventListener('click', run);
  results.querySelectorAll('.clear-facets').forEach((b) => {
    b.addEventListener('click', () => { activeFacets = new Set(); render(); });
  });
  results.querySelectorAll('.clear-choice').forEach((b) => {
    b.addEventListener('click', () => { chosen = ''; render(); });
  });
  results.querySelectorAll('[data-choice]').forEach((b) => {
    b.addEventListener('click', () => { chosen = b.dataset.choice; render(); });
  });
  results.querySelectorAll('[data-facet]').forEach((b) => {
    b.addEventListener('click', () => {
      const code = b.dataset.facet;
      activeFacets.has(code) ? activeFacets.delete(code) : activeFacets.add(code);
      render();
    });
  });
}

const REQUEST_TIMEOUT_MS = 150000;

function failure(err) {
  // fetch rejects with a TypeError when nothing is listening — by far the most
  // common cause here, and the one with a concrete fix.
  if (err.name === 'AbortError') {
    return `<section class="overview" data-empty="true">
      <h2>The lookup timed out.</h2>
      <p class="detail">No answer after two and a half minutes. One of the four
        catalogues is probably not responding.</p>
      <p class="qualifier">Whatever did come back is cached, so trying again is
        usually much faster than the first attempt.</p>
    </section>`;
  }
  if (err instanceof TypeError) {
    return `<section class="overview" data-empty="true">
      <h2>Can&rsquo;t reach the server.</h2>
      <p class="detail">The page loaded, but <code>/api/lookup</code> got no
        response — the server is no longer running, or was restarted while this
        tab was open.</p>
      <p class="qualifier">Start it with <code>python server.py</code>, then
        reload this page.</p>
    </section>`;
  }
  return `<section class="overview" data-empty="true">
    <h2>The lookup did not finish.</h2>
    <p class="detail">${esc(err.message)}</p>
    <p class="qualifier">The catalogues are reached live; if one is down, try again shortly.</p>
  </section>`;
}

async function run() {
  const params = new URLSearchParams();
  ['title', 'author', 'year_from', 'year_to', 'publisher'].forEach((id) => {
    const v = document.getElementById(id).value.trim();
    if (v) params.set(id, v);
  });
  if (!params.get('title') && !params.get('author')) {
    results.innerHTML = `<section class="overview" data-empty="true">
      <h2>Enter a title or an author.</h2>
      <p class="byline">A year or publisher on its own is a filter, not a search.</p>
    </section>`;
    document.getElementById('title').focus();
    return;
  }

  activeFacets = new Set();
  chosen = '';
  submit.setAttribute('aria-busy', 'true');
  submit.textContent = 'Looking…';
  results.innerHTML = `<p class="waiting">Searching the catalogues…</p>
    <p class="waiting-note">Four catalogues, queried live. A title you have not
      looked up before can take up to a minute; the same lookup again is instant.</p>`;

  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`/api/lookup?${params}`, { signal: abort.signal });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `the server returned ${res.status}`);
    report = data;
    render();
  } catch (err) {
    results.innerHTML = failure(err);
  } finally {
    clearTimeout(timer);
    submit.removeAttribute('aria-busy');
    submit.textContent = 'Look up';
  }
}

form.addEventListener('submit', (e) => { e.preventDefault(); run(); });

const FILTER_IDS = ['year_from', 'year_to', 'publisher'];

function describeFilters() {
  const active = FILTER_IDS
    .map((id) => [id, document.getElementById(id).value.trim()])
    .filter(([, v]) => v);
  if (!active.length) {
    filtersToggle.textContent = 'Narrow by year or publisher';
    filtersToggle.classList.remove('active');
    return;
  }
  const parts = [];
  const from = document.getElementById('year_from').value.trim();
  const to = document.getElementById('year_to').value.trim();
  const pub = document.getElementById('publisher').value.trim();
  if (from || to) parts.push(`${from || 'any'}\u2013${to || 'any'}`);
  if (pub) parts.push(pub);
  filtersToggle.textContent = `Narrowed to ${parts.join(', ')} — clear`;
  filtersToggle.classList.add('active');
}

filtersToggle.addEventListener('click', () => {
  // Once filters are set, the button clears them rather than just collapsing —
  // the whole problem is a filter you cannot see still applying.
  if (filtersToggle.classList.contains('active')) {
    FILTER_IDS.forEach((id) => { document.getElementById(id).value = ''; });
    describeFilters();
    filters.hidden = false;
    filtersToggle.setAttribute('aria-expanded', 'true');
    return;
  }
  const open = filtersToggle.getAttribute('aria-expanded') === 'true';
  filtersToggle.setAttribute('aria-expanded', String(!open));
  filters.hidden = open;
});

FILTER_IDS.forEach((id) =>
  document.getElementById(id).addEventListener('input', describeFilters));

document.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (e.key === '/' && !typing) {
    e.preventDefault();
    document.getElementById('title').focus();
  }
  if (e.key === 'Escape') {
    if (typing) document.activeElement.blur();
    results.querySelectorAll('.more[open]').forEach((d) => { d.open = false; });
  }
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !typing) {
    const items = [...results.querySelectorAll('.edition')];
    if (!items.length) return;
    e.preventDefault();
    const at = items.indexOf(document.activeElement.closest('.edition'));
    const next = e.key === 'ArrowDown' ? Math.min(at + 1, items.length - 1) : Math.max(at - 1, 0);
    items[at === -1 ? 0 : next].focus();
  }
});

fetch('/api/health')
  .then((r) => r.json())
  .then((h) => { sourcesLine.textContent = `Sources: ${(h.sources || []).join(' \u00b7 ')}`; })
  .catch(() => {});
