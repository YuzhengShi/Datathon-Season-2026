// How the site words an amount (dist/model.js): a stated range is a range, never one figure and never "varies";
// nothing stated is "Funding varies", never $0.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

async function load(mode) {
  const context = vm.createContext({ fetch: async () => ({ ok: true, json: async () => ({ data_mode: mode, records: [] }) }) });
  vm.runInContext(fs.readFileSync(path.join(root, 'dist/model.js'), 'utf8'), context, { filename: 'dist/model.js' });
  await context.FundingModel.ready;
  return context.FundingModel;
}

test('a figure, a range and nothing at all are told apart', async () => {
  const M = await load('live');
  assert.equal(M.amountText({ amount: 1000, amount_details: { kind: 'fixed' } }), '$1,000');
  assert.equal(M.amountText({ amount: null, amount_details: { kind: 'range', minimum: 2000, maximum: 4000 } }), '$2,000\u2013$4,000');
  assert.equal(M.amountText({ amount: null, amount_details: { kind: 'unspecified' } }), 'Funding varies');
  assert.equal(M.amountText({ amount: null }), 'Funding varies');
  assert.equal(M.amountText({}), 'Funding varies'); // a record without the field is not "$NaN"
  assert.equal(M.amountText({ amount: null, amount_details: { kind: 'range', minimum: null, maximum: 4000 } }), 'Funding varies', 'half a range is not shown');
});

test('hasAmount counts a figure or a complete range, nothing else', async () => {
  const M = await load('live');
  assert.equal(M.hasAmount({ amount: 0, amount_details: { kind: 'fixed' } }), true, 'zero is a figure, only null is unknown');
  assert.equal(M.hasAmount({ amount: null, amount_details: { kind: 'range', minimum: 1, maximum: 2 } }), true);
  assert.equal(M.hasAmount({ amount: null, amount_details: { kind: 'range', minimum: 1, maximum: null } }), false);
  assert.equal(M.hasAmount({ amount: null, amount_details: { kind: 'variable' } }), false);
  assert.equal(M.hasAmount({ amount: undefined }), false);
});

test('the note says what a figure is: fixed, up to, listed range', async () => {
  const live = await load('live');
  assert.equal(live.amountNote({ amount: 500, amount_details: { kind: 'fixed' } }), 'Listed amount');
  assert.equal(live.amountNote({ amount: 500, amount_details: { kind: 'maximum' } }), 'Up to');
  assert.equal(live.amountNote({ amount: null, amount_details: { kind: 'range', minimum: 1, maximum: 2 } }), 'Listed range');
  assert.equal(live.amountNote({ amount: null, amount_details: { kind: 'unspecified' } }), 'Confirm amount');
  const demo = await load('demo');
  assert.equal(demo.amountNote({ amount: null, amount_details: { kind: 'range', minimum: 1, maximum: 2 } }), 'Listed range \u00b7 example');
});
