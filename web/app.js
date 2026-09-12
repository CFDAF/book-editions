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

const text = (s) => (s == null ? '' : String(s));
const esc = (s) => text(s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ------------------------------------------------------------------ helpers */

function joined(parts, className = 'sep') {
  return parts.filter(Boolean).join(`<span class="${className}">&middot;</span>`);
}

function year(e) {
  // Open Library dates arrive in every shape going ('June 1985', '1972-01-01').
  const m = text(e.year).match(/\b(1[0-9]{3}|20[0-9]{2})\b/);
  return m ? m[1] : text(e.year);
}

/* ------------------------------------------------------------------- render */

function renderVerdict(r) {
  const v = r.verdict;
  const c = r.cluster || {};
  let origin = '';
  if (c.qid) {
    const bits = joined([
      c.original_title ? `<cite>${esc(c.original_title)}</cite>` : null,
      c.original_language ? esc(r.language_names?.[c.original_language] || c.original_language) : null,
      c.original_year ? esc(c.original_year) : null,
    ]);
    origin = `<p class="origin"><span class="label">Written as</span>${bits}
      <span class="sep">&middot;</span><a href="${esc(c.url)}" target="_blank" rel="noopener">Wikidata</a></p>`;
  }

  // When nothing corroborates the answer, say so here rather than dressing the
  // headline up as certainty.
  const soft = ['low', 'unconfirmed'].includes(v.confidence) && v.has_italian;
  const qualifier = soft
    ? '<p class="qualifier">Nothing corroborates this beyond a title and author match — treat it as a lead, not a finding.</p>'
    : '';

  return `<section class="verdict" data-confidence="${esc(v.confidence)}" data-found="${!!v.has_italian}">
    <h2>${esc(v.headline)}</h2>
    ${v.detail ? `<p class="detail">${esc(v.detail)}</p>` : ''}
    ${qualifier}
    ${origin}
  </section>`;
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
  const role = e.role !== 'reprint' ? `<span class="role">${esc(e.role)}</span>` : '';
  const others = (e.available_languages || [])
    .filter((c) => c !== e.language)
    .map((c) => report?.language_names?.[c] || c);
  const imprint = joined([
    e.publisher ? esc(e.publisher) : null,
    year(e) ? esc(year(e)) : null,
    e.series ? esc(e.series) : null,
    e.isbn ? `<span class="isbn">${esc(e.isbn)}</span>` : null,
    e.edition_count ? `${e.edition_count} edition${e.edition_count === 1 ? '' : 's'}` : null,
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

  const shelf = [e.dewey, e.sbn_bid].filter(Boolean).join('  ');

  return `<li class="edition" tabindex="-1">
    <div class="edition-head">
      <span class="edition-title">${role}${esc(e.title)}</span>
      ${shelf ? `<span class="shelfmark">${esc(shelf)}</span>` : ''}
    </div>
    ${imprint ? `<p class="imprint">${imprint}</p>` : ''}
    ${evidence}
    <details class="more"><summary>Details</summary>
      <div class="more-body">${rows.join('')}</div>
    </details>
  </li>`;
}

// These counts are SBN's own, across every record the search touched — not
// counts of what is listed below. Offering all of them as filters meant
// clicking a language we hold no editions in emptied the page for no stated
// reason. Only languages actually present are clickable now; the rest are shown
// as what they are, context from the catalogue.
function facetRow(r) {
  const langFacet = (r.facets || []).find((f) => f.facetName === 'lingua');
  if (!langFacet) return '';
  const present = new Set(Object.keys(r.editions_by_language || {}));
  let filterable = 0;

  const items = langFacet.facetValues.slice(0, 8).map(([label, code, count]) => {
    const n = `<span class="count">${esc(count)}</span>`;
    if (present.has(code)) {
      filterable += 1;
      return `<button type="button" data-facet="${esc(code)}"
        aria-pressed="${activeFacets.has(code)}">${esc(label)} ${n}</button>`;
    }
    return `<span class="absent" title="SBN holds ${esc(count)} record(s) in ${esc(label)}, but none of them matched this work">${esc(label)} ${n}</span>`;
  }).join('<span class="sep">/</span>');

  const note = filterable < langFacet.facetValues.slice(0, 8).length
    ? `<span class="facets-note">Greyed languages are records SBN holds for this
        search that did not match this work.</span>`
    : '';
  return `<p class="facets"><span class="label">In SBN</span> ${items} ${note}</p>`;
}

function render() {
  const r = report;
  const groups = Object.entries(r.editions_by_language || {});
  const body = groups.map(([code, editions]) => {
    const shown = activeFacets.size ? editions.filter((e) => activeFacets.has(e.language)) : editions;
    if (!shown.length) return '';
    return `<section class="group">
      <div class="group-body">
        <div class="spine">
          <span class="code">${code === 'unknown' ? '&mdash;' : esc(code)}</span>
          <span class="name">${esc(r.language_names?.[code] || '')}</span>
          <span class="count">${shown.length}</span>
        </div>
        <ul class="editions">${shown.map(renderEdition).join('')}</ul>
      </div>
    </section>`;
  }).join('');

  const notes = (r.notes || [])
    .filter((n) => !n.startsWith('Incomplete:'))
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
  // language having no editions.
  const partial = Object.entries(r.sources || {})
    .filter(([, state]) => String(state).startsWith('partial'));
  const warning = partial.length
    ? `<p class="incomplete"><strong>Some editions are probably missing.</strong>
        ${partial.map(([n, s]) => `${esc(n)} — ${esc(s.replace('partial ', ''))}`).join('; ')}.
        Whatever arrived is cached, so searching again is quick and usually fills the gaps.
        <button type="button" id="retry">Search again</button></p>`
    : '';

  // A filter that hides everything should say so, not render a blank page.
  const empty = activeFacets.size && !body
    ? `<p class="nothing">Nothing in the chosen language. <button type="button"
         id="clear-facets">Show all languages</button></p>`
    : '';
  results.innerHTML = renderVerdict(r) + warning + facetRow(r) + body + empty + notesHtml;
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
  const clear = document.getElementById('clear-facets');
  if (clear) clear.addEventListener('click', () => { activeFacets = new Set(); render(); });
  results.querySelectorAll('.facets button').forEach((b) => {
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
    return `<section class="verdict" data-found="false">
      <h2>The lookup timed out.</h2>
      <p class="detail">No answer after two and a half minutes. One of the four
        catalogues is probably not responding.</p>
      <p class="qualifier">Whatever did come back is cached, so trying again is
        usually much faster than the first attempt.</p>
    </section>`;
  }
  if (err instanceof TypeError) {
    return `<section class="verdict" data-found="false">
      <h2>Can&rsquo;t reach the server.</h2>
      <p class="detail">The page loaded, but <code>/api/lookup</code> got no
        response — the server is no longer running, or was restarted while this
        tab was open.</p>
      <p class="qualifier">Start it with <code>python server.py</code>, then
        reload this page.</p>
    </section>`;
  }
  return `<section class="verdict" data-found="false">
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
    results.innerHTML = `<section class="verdict" data-found="false">
      <h2>Enter a title or an author.</h2>
      <p class="detail">A year or publisher on its own is a filter, not a search.</p>
    </section>`;
    document.getElementById('title').focus();
    return;
  }

  activeFacets = new Set();
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

document.querySelectorAll('.example').forEach((b) => {
  b.addEventListener('click', () => {
    document.getElementById('title').value = b.dataset.title;
    document.getElementById('author').value = b.dataset.author || '';
    run();
  });
});

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
  .then((h) => { if (h.google_books !== 'configured') {
    sourcesLine.textContent = 'Google Books needs GOOGLE_BOOKS_API_KEY; the other three sources need nothing.';
  } })
  .catch(() => {});
