---
name: algorithms
description: Design, analyse and implement algorithms and data structures - complexity, common patterns, tests.
category: coding
tools: write_file, run_shell
status: live
---
# Algorithms

1. Restate the problem with input size limits; pick a target complexity (n ≤ 10⁵ → O(n log n); n ≤ 20 → exponential is OK).
2. Patterns to consider:
   - Hash map / set: counting, dedupe, two-sum style lookups - O(n).
   - Two pointers / sliding window: sorted arrays, substrings with constraints.
   - Sorting + greedy: intervals, scheduling (prove the greedy choice or find a counterexample).
   - Binary search: on sorted data or on the answer (monotonic predicate).
   - BFS (shortest path, unweighted), Dijkstra (non-negative weights), topological sort (dependencies), union-find (connectivity).
   - Dynamic programming: define state, transition, base case, order; memoise first, then tabulate.
   - Heaps: top-k, merging sorted lists, running median. Prefix sums: range queries.
   - Backtracking with pruning: permutations, subsets, constraint search.
3. Write the solution with clear names, then a brute-force version for small inputs.
4. Test: edge cases (empty, one element, duplicates, negatives, max size) and a randomised comparison with brute force (`run_shell`).
5. Report time and space complexity with a one-line justification.
