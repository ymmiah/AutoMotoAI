'use strict';
function combined(a, b) {
  if (!Number.isInteger(a) || !Number.isInteger(b)) {
    throw new TypeError('Integers are required.');
  }
  return a + b;
}
module.exports = {combined};
