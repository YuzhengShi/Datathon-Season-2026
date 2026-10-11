// Runs dist/model.js (what the site does in the browser) on the records and filter cases a Python test hands in,
// and prints what the page would show. Used by tests/test_filter_parity.py; it makes no network request.
//   node tests/js/parity.mjs <input.json>
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const dataset = { data_mode: input.data_mode, records: input.records };

// The page fetches data/opportunities.json; here the fetch returns the records the test supplies.
const context = vm.createContext({
  fetch: async () => ({ ok: true, json: async () => JSON.parse(JSON.stringify(dataset)) }),
});
vm.runInContext(fs.readFileSync(path.join(root, 'dist', 'model.js'), 'utf8'), context, { filename: 'dist/model.js' });
await context.FundingModel.ready;
const M = context.FundingModel;

const out = { results: {}, statistics: {} };
for (const c of input.cases) {
  const state = M.fromFilters({ ...input.defaults, ...c.filters });
  out.results[c.name] = M.getResults(state).map((x) => x.id);
  if (c.statistics) {
    const s = M.statistics(state);
    out.statistics[c.name] = {
      total: s.total,
      national: s.national_count,
      regional: s.regional_count,
      unspecified: s.unspecified_region_count,
      regions: s.regions.map((r) => [r.code, r.regional_count, r.national_count, r.reach_count]),
      by_type: s.by_type,
      by_community: s.by_community,
      listed: s.amounts.listed,
      unknown: s.amounts.unknown,
      highest: s.amounts.highest_example_figure === null ? null : Number(s.amounts.highest_example_figure),
      bands: s.amount_bands,
      by_deadline_kind: s.by_deadline_kind,
      verified: s.quality.verified_records,
      unknown_education: s.quality.unknown_education_level,
    };
  }
}
process.stdout.write(JSON.stringify(out));
