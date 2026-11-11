'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {combined} = require('../src/bridge.cjs');

test('V25 React Native bridge logic', () => {
  assert.equal(combined(20, 22), 42);
  assert.throws(() => combined('20', 22), TypeError);
});
