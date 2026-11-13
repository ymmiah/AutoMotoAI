% V28 Octave/MATLAB-compatible numerical fixture; no external libraries.
values = csvread("data/measurements.csv", 1, 0);
assert(numel(values) == 5);
fprintf("V28_OCTAVE_PASS count=%d sum=%d mean=%d\n", numel(values), sum(values), mean(values));
