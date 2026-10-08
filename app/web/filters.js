/* The three filters, as a pure function of a snapshot and a filter state.
 *
 * It is a module of its own, and it is pure, for two reasons that are the same
 * reason. The page must re-filter what it already holds and issue **no**
 * request (Step 10's gate, build rule 12), so the whole of filtering has to be
 * expressible without a fetch; and a rule that is expressible without a fetch
 * could be run over real recorded snapshots, which is how the gate's
 * arithmetic was checked rather than eyeballed.
 *
 * **Nothing here re-derives anything `core/` already decided.** The year each
 * row is filtered on is `year_num`, which `core.view.year_of` parsed — the same
 * reading the header's "earliest edition found" used, so a filtered list cannot
 * disagree with the header above it. The publisher is `publisher_ids`, which is
 * `core.fold.publisher_key`'s rule for "the same house" — measured once, in
 * Python, and never re-implemented here.
 *
 * **Filters never touch identity** (rule 12). Nothing in this file reads
 * `snapshot.header`, and the counts it compares against are the unfiltered
 * ones. A filter changes which rows are drawn and nothing else.
 */

export const UNKNOWN = 'unknown';

/** No filter at all: everything is shown. */
export function emptyState() {
  return { languages: [], publishers: [], yearFrom: null, yearTo: null };
}

export function isEmpty(state) {
  return !state.languages.length && !state.publishers.length
    && state.yearFrom === null && state.yearTo === null;
}

/* Why one row is not shown. The order is a precedence, not a preference: a row
 * can fail several filters at once and is charged to exactly the first that
 * applies, so the reasons **partition** the hidden rows and their counts sum to
 * `hidden`. The two classes the plan names — a row with no language at all
 * (19.2% of Open Library editions) and a row with no parsable year — come
 * first, so that whenever one of them is hidden it is hidden *by name*. */
const REASONS = ['no-language', 'other-language', 'no-year', 'outside-years',
  'other-publisher'];

function why(row, state) {
  if (state.languages.length && !state.languages.includes(row.language)) {
    return row.language === UNKNOWN ? 'no-language' : 'other-language';
  }
  if (state.yearFrom !== null || state.yearTo !== null) {
    // Every printing, not the first: a row printed in 1985 and 2026 was on sale
    // in 2026, and a filter from 2000 that hid it would be wrong about the row
    // (decision AG). `years_num` is `core.view.year_of` over each printing.
    const years = row.years_num
      ?? (row.year_num === null || row.year_num === undefined ? [] : [row.year_num]);
    if (!years.length) return 'no-year';
    const inside = years.some((y) => (state.yearFrom === null || y >= state.yearFrom)
      && (state.yearTo === null || y <= state.yearTo));
    if (!inside) return 'outside-years';
  }
  if (state.publishers.length
      && !(row.publisher_ids || []).some((id) => state.publishers.includes(id))) {
    return 'other-publisher';
  }
  return null;
}

function span(from, to) {
  if (from !== null && to !== null) return `${from}–${to}`;
  if (from !== null) return `${from} or later`;
  return `${to} or earlier`;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * `{groups, shown, total, hidden, reasons, languagesShown, languagesTotal}`.
 *
 * `groups` holds only the languages with a row left, each carrying both counts:
 * `editions` is what the language has unfiltered and never moves, `rows` is
 * what is drawn.
 */
export function apply(snapshot, state) {
  const spans = new Map((snapshot.header?.spans || []).map((s) => [s.code, s]));
  const order = snapshot.language_order || Object.keys(snapshot.editions_by_language || {});
  const groups = [];
  const hiddenBy = new Map(REASONS.map((r) => [r, []]));
  let shown = 0;
  let total = 0;

  for (const code of order) {
    const rows = snapshot.editions_by_language?.[code] || [];
    total += rows.length;
    const kept = [];
    for (const row of rows) {
      const reason = why(row, state);
      if (reason === null) kept.push(row);
      else hiddenBy.get(reason).push(row);
    }
    shown += kept.length;
    if (kept.length) {
      const s = spans.get(code) || {};
      groups.push({
        code,
        name: s.name || code,
        is_original: !!s.is_original,
        first_year: s.first_year ?? null,
        last_year: s.last_year ?? null,
        editions: rows.length,
        rows: kept,
      });
    }
  }

  const reasons = [];
  for (const kind of REASONS) {
    const rows = hiddenBy.get(kind);
    if (!rows.length) continue;
    reasons.push({ kind, count: rows.length, text: phrase(kind, rows, state) });
  }

  return {
    groups,
    shown,
    total,
    hidden: total - shown,
    reasons,
    languagesShown: groups.length,
    languagesTotal: order.length,
  };
}

function phrase(kind, rows, state) {
  switch (kind) {
    case 'no-language':
      return `${rows.length} whose language no source recorded`;
    case 'other-language': {
      const codes = new Set(rows.map((r) => r.language));
      return `${rows.length} in ${plural(codes.size, 'other language', 'other languages')}`;
    }
    case 'no-year':
      return `${rows.length} with no certain year`;
    case 'outside-years':
      return `${rows.length} published outside ${span(state.yearFrom, state.yearTo)}`;
    default:
      return `${rows.length} from other publishers`;
  }
}

/** The one-line summary, built from the unfiltered totals. */
export function summary(result) {
  const editions = plural(result.shown, 'edition', 'editions');
  const head = `Showing ${editions} of ${result.total}, in `
    + `${result.languagesShown} of ${plural(result.languagesTotal, 'language', 'languages')}.`;
  if (!result.hidden) return head;
  return `${head} ${result.hidden} hidden: `
    + result.reasons.map((r) => r.text).join(' · ');
}
