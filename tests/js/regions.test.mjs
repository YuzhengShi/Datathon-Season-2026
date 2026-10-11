// The numbers behind the province and territory part of the Statistics page (dist/regions.js) and the map that draws them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const live = JSON.parse(read('dist/data/opportunities.json'));
const geometry = JSON.parse(read('dist/data/canada-map.json'));
const plain = (value) => JSON.parse(JSON.stringify(value)); // values from a vm context have another realm's prototypes

async function load(records, mode = 'live') {
  const context = vm.createContext({ fetch: async () => ({ ok: true, json: async () => ({ data_mode: mode, records }) }) });
  for (const file of ['dist/model.js', 'dist/regions.js']) vm.runInContext(read(file), context, { filename: file });
  await context.FundingModel.ready;
  return context;
}
const row = (over = {}) => ({ id: 'x', title: 'T', provider: 'P', type: 'Scholarship', community: ['First Nations'], province: 'Ontario', amount: null, deadline_kind: 'unspecified', source_kind: 'official_page', ...over });

test('every record lands in exactly one place, and the region counts equal the ones the page already shows', async () => {
  const ctx = await load(live.records);
  const rows = ctx.FundingModel.getResults({});
  const summary = plain(ctx.FundingRegions.summarize(rows, ctx.FundingModel.regions));
  const regionTotal = summary.regions.reduce((sum, r) => sum + r.regional, 0);
  assert.equal(regionTotal + summary.nationwide.count + summary.unstated.count, rows.length);
  const stats = plain(ctx.FundingModel.statistics({}));
  assert.equal(summary.nationwide.count, stats.national_count);
  assert.equal(summary.unstated.count, stats.unspecified_region_count);
  for (const region of summary.regions) {
    const shown = stats.regions.find((x) => x.code === region.code);
    assert.deepEqual([region.regional, region.nationwide, region.reach], [shown.regional_count, shown.national_count, shown.reach_count], region.name);
    assert.equal(region.directory + region.verified, region.regional, region.name);
  }
});

test('the published dataset has records for every province and territory', async () => {
  const ctx = await load(live.records);
  const summary = plain(ctx.FundingRegions.summarize(ctx.FundingModel.getResults({}), ctx.FundingModel.regions));
  const empty = summary.regions.filter((r) => r.regional === 0).map((r) => r.name);
  assert.deepEqual(empty, [], `no region-specific record for: ${empty.join(', ')}`);
  assert.equal(summary.covered, 13);
});

test('a region name the page does not know is counted as not stated, never dropped or guessed', async () => {
  const ctx = await load([row({ province: 'Atlantis' }), row({ province: null }), row({ province: 'all' }), row({ province: 'Yukon' })]);
  const summary = plain(ctx.FundingRegions.summarize(ctx.FundingModel.getResults({}), ctx.FundingModel.regions));
  assert.deepEqual([summary.unstated.count, summary.nationwide.count, summary.regions.find((r) => r.code === 'YT').regional], [2, 1, 1]);
});

test('describe reports what the records state and leaves the rest unknown', async () => {
  const ctx = await load([]);
  const d = plain(ctx.FundingRegions.describe([
    row({ amount: 1000, provider: 'B', source_modified_at: '2012-11-29', source_kind: 'directory_listing', community: ['Inuit', 'Métis'] }),
    row({ amount: 5000, provider: 'A', source_modified_at: '2025-03-01' }),
    row({ amount: null, provider: 'A' }),
  ]));
  assert.deepEqual([d.count, d.directory, d.verified, d.listed, d.lowest, d.highest], [3, 1, 2, 2, 1000, 5000]); // unknown is not zero
  assert.deepEqual([d.oldest, d.newest], [2012, 2025]);
  assert.deepEqual(d.providers, [{ name: 'A', count: 2 }, { name: 'B', count: 1 }]);
  assert.deepEqual(d.community, { 'First Nations': 2, Inuit: 1, 'Métis': 1 });
  const none = plain(ctx.FundingRegions.describe([]));
  assert.deepEqual([none.lowest, none.highest, none.oldest, none.newest], [null, null, null, null]);
});

test('the colour scale cuts classes from the data, keeps 0 apart and never leaves the top class empty', async () => {
  const ctx = await load([]);
  const { scale } = ctx.FundingRegions;
  const flat = plain(scale([0, 0, 0]));
  assert.deepEqual(flat.legend.map((l) => l.label), ['0']);
  assert.equal(scale([0, 0, 0]).classOf(0), 0);
  assert.deepEqual(plain(scale([0, 5])).legend.map((l) => l.label), ['0', '1+']);
  const counts = [130, 124, 64, 62, 51, 28, 20, 15, 13, 7, 6, 4, 3, 2, 2, 0];
  const s = scale(counts);
  const classes = counts.map((v) => s.classOf(v));
  assert.equal(s.classOf(0), 0);
  assert.ok(counts.filter((v) => v > 0).every((v) => s.classOf(v) >= 1));
  const top = Math.max(...classes);
  assert.ok(classes.filter((c) => c === top).length >= 1);
  assert.equal(s.classOf(130), top);
  const sorted = [...counts].sort((a, b) => a - b).map((v) => s.classOf(v));
  assert.deepEqual(sorted, [...sorted].sort((a, b) => a - b)); // a bigger count is never a lighter colour
  const legend = plain(s.legend).slice(1); // the ranges of the non-zero classes are contiguous
  for (let i = 1; i < legend.length; i += 1) assert.equal(legend[i].min, legend[i - 1].max + 1);
  assert.equal(legend.at(-1).max, null); // Infinity does not survive JSON; the top class is open-ended
  assert.ok(legend.length >= 4 && legend.length <= 5);
});

test('the tile map has one distinct tile for each of the 13 regions', async () => {
  const ctx = await load([]);
  const tiles = plain(ctx.FundingRegions.TILES);
  assert.deepEqual(Object.keys(tiles).sort(), Object.keys(ctx.FundingModel.regions).sort());
  assert.equal(new Set(Object.values(tiles).map((p) => p.join(','))).size, 13);
  assert.ok(Object.values(tiles).every(([c, r]) => c >= 1 && c <= 7 && r >= 1 && r <= 4));
});

test('the map has north at the top and west on the left', () => {
  const at = Object.fromEntries(geometry.regions.map((r) => [r.code, r.label]));
  assert.equal(geometry.regions.length, 13);
  assert.equal(geometry.orientation, 'north-up');
  assert.ok(at.YT[1] < at.BC[1], 'Yukon is north of British Columbia');
  assert.ok(at.NT[1] < at.AB[1], 'the Northwest Territories are north of Alberta');
  assert.ok(at.NU[1] < at.ON[1], 'Nunavut is north of Ontario');
  assert.ok(at.NS[1] > at.QC[1] && at.NS[0] > at.QC[0], 'Nova Scotia is south-east of Quebec');
  assert.ok(at.BC[0] < at.AB[0] && at.AB[0] < at.ON[0] && at.ON[0] < at.NL[0], 'west to east: BC, AB, ON, NL');
});

test('source mix, source age and top providers add up to the records they were given', async () => {
  const ctx = await load([]);
  const rows = [
    row({ source_kind: 'directory_listing', source_modified_at: '2012-01-01', provider: 'B' }),
    row({ source_kind: 'directory_listing', source_modified_at: '2017-06-01', provider: 'B' }),
    row({ source_kind: 'directory_listing', source_modified_at: '2025-02-02', provider: 'C' }),
    row({ provider: 'A' }),
  ];
  assert.deepEqual(plain(ctx.FundingRegions.sourceMix(rows)), { directory: 3, verified: 1 });
  const age = plain(ctx.FundingRegions.currency(rows));
  assert.deepEqual(age.groups.map((g) => g.count), [1, 1, 0, 1]);
  assert.equal(age.unknown, 1);
  assert.equal(age.groups.reduce((s, g) => s + g.count, 0) + age.unknown, rows.length);
  assert.deepEqual(plain(ctx.FundingRegions.topProviders(rows, 2)), [{ name: 'B', count: 2 }, { name: 'A', count: 1 }]);
});
