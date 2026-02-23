Rare eta/eta' to 4-muon replication
===================================

This example reproduces the core workflow from your poster:

1. Generate minimum-bias `pp` collisions at `sqrt(s) = 13 TeV`.
2. Force `eta (221)` and `eta' (331)` decays to `mu+ mu- mu+ mu-` to probe
   detector acceptance independently of unknown branching ratios.
3. Apply LHCb-like cuts:
   - all 4 muons satisfy `2 < eta < 5`
   - two leading muons: `pT > 0.5 GeV`
   - two trailing muons: `pT > 0.1 GeV`
4. Print per-event yields, cut efficiencies, and estimated observed counts using:
   - `sigma = 100 mb`
   - `L = 5 fb^-1`
   - `BR(eta->4mu) = 5e-9`
   - `BR(eta'->4mu) = 1.7e-8`

Build and run
-------------

From the repository root:

```bash
make -C examples mymain_eta4mu
cd examples
./mymain_eta4mu 10000 8310
```

Arguments:

- `argv[1]` = number of events (default: `10000`)
- `argv[2]` = RNG seed (default: `8310`)

Notes
-----

- The decay channels are forced to BR=1 inside the generator so acceptance can
  be measured directly; physical BR values are re-applied only when computing
  estimated observed event counts.
- This is a generator-level replication, not a full detector simulation.
