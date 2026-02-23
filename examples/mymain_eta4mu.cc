// Rare eta/eta' -> 4 muon replication study for LHCb-like acceptance cuts.

#include "Pythia8/Pythia.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

using namespace Pythia8;

namespace {

struct MesonCounts {
  long long produced = 0;
  long long passEta = 0;
  long long passEtaPt = 0;
};

void collectFinalMuonDaughters(const Event& event, int i, vector<int>& muons) {
  int d1 = event[i].daughter1();
  int d2 = event[i].daughter2();
  if (d1 <= 0 || d2 < d1) return;

  for (int d = d1; d <= d2; ++d) {
    if (d <= 0 || d >= event.size()) continue;
    if (event[d].isFinal()) {
      if (std::abs(event[d].id()) == 13) muons.push_back(d);
      continue;
    }
    collectFinalMuonDaughters(event, d, muons);
  }
}

bool inLHCbEta(double eta) {
  return (eta > 2.0 && eta < 5.0);
}

void fillCounts(const Event& event, int iMeson, MesonCounts& c) {
  c.produced++;

  vector<int> muons;
  muons.reserve(8);
  collectFinalMuonDaughters(event, iMeson, muons);
  if (muons.size() != 4) return;

  array<double, 4> pts{};
  for (int i = 0; i < 4; ++i) {
    const Particle& mu = event[muons[i]];
    if (!inLHCbEta(mu.eta())) return;
    pts[i] = mu.pT();
  }
  c.passEta++;

  sort(pts.begin(), pts.end(), std::greater<double>());
  if (pts[0] > 0.5 && pts[1] > 0.5 && pts[2] > 0.1 && pts[3] > 0.1) {
    c.passEtaPt++;
  }
}

void printSummary(const string& name, const MesonCounts& c, int nGenEvents, double br,
                  double sigmaMb = 100.0, double lumiFb = 5.0) {
  cout << fixed << setprecision(6);
  double producedPerEvent = double(c.produced) / double(nGenEvents);
  double passEtaPerEvent = double(c.passEta) / double(nGenEvents);
  double passEtaPtPerEvent = double(c.passEtaPt) / double(nGenEvents);
  double passEtaFrac = (c.produced > 0)
      ? double(c.passEta) / double(c.produced) : 0.0;
  double passEtaPtFrac = (c.produced > 0)
      ? double(c.passEtaPt) / double(c.produced) : 0.0;

  // 1 mb * 1 fb^-1 = 1e12 collisions.
  double nCollisions = sigmaMb * lumiFb * 1e12;
  double estObserved = nCollisions * passEtaPtPerEvent * br;

  cout << "\n" << name << " summary\n";
  cout << "  produced/event                 = " << producedPerEvent << "\n";
  cout << "  pass eta(2<eta<5)/event        = " << passEtaPerEvent << "\n";
  cout << "  pass eta+pT/event              = " << passEtaPtPerEvent << "\n";
  cout << "  pass eta fraction              = " << passEtaFrac << "\n";
  cout << "  pass eta+pT fraction           = " << passEtaPtFrac << "\n";
  cout << "  estimated observed events      = " << estObserved
       << "  (sigma=" << sigmaMb << " mb, L=" << lumiFb
       << " fb^-1, BR=" << std::scientific << br << std::defaultfloat << ")\n";
  cout << fixed << setprecision(6);
}

} // namespace

int main(int argc, char* argv[]) {
  int nEvents = 10000;
  int seed = 8310;
  if (argc > 1) nEvents = std::max(1, atoi(argv[1]));
  if (argc > 2) seed = std::max(1, atoi(argv[2]));

  Pythia pythia;
  pythia.readString("Beams:idA = 2212");
  pythia.readString("Beams:idB = 2212");
  pythia.readString("Beams:eCM = 13000.");
  pythia.readString("Print:init = off");
  pythia.readString("Print:next = off");
  pythia.readString("Print:quiet = on");
  pythia.readString("SoftQCD:inelastic = on");
  pythia.readString("Init:showProcesses = off");
  pythia.readString("Init:showMultipartonInteractions = off");
  pythia.readString("Init:showChangedSettings = off");
  pythia.readString("Init:showChangedParticleData = off");
  pythia.readString("Next:numberShowInfo = 0");
  pythia.readString("Next:numberShowProcess = 0");
  pythia.readString("Next:numberShowEvent = 0");

  // Force rare channels to expose kinematic acceptance independent of BR.
  pythia.readString("221:onMode = off");
  pythia.readString("221:addChannel = 1 1.0 0 13 -13 13 -13");
  pythia.readString("331:onMode = off");
  pythia.readString("331:addChannel = 1 1.0 0 13 -13 13 -13");

  pythia.readString("Random:setSeed = on");
  pythia.readString("Random:seed = " + to_string(seed));

  pythia.init();

  MesonCounts etaCounts;
  MesonCounts etaPrimeCounts;
  int nGenerated = 0;

  for (int iEvent = 0; iEvent < nEvents; ++iEvent) {
    if (!pythia.next()) continue;
    nGenerated++;
    for (int i = 0; i < pythia.event.size(); ++i) {
      if (pythia.event[i].daughter1() <= 0) continue;
      int id = pythia.event[i].id();
      if (id == 221) fillCounts(pythia.event, i, etaCounts);
      if (id == 331) fillCounts(pythia.event, i, etaPrimeCounts);
    }
  }

  if (nGenerated == 0) {
    cerr << "No events were generated successfully.\n";
    return 1;
  }

  cout << fixed << setprecision(6);
  cout << "\nReplication setup:\n";
  cout << "  attempted events = " << nEvents << "\n";
  cout << "  generated events = " << nGenerated << "\n";
  cout << "  seed   = " << seed << "\n";
  cout << "  cuts   = all 4 muons in 2<eta<5, pT(lead2)>0.5 GeV, pT(trail2)>0.1 GeV\n";
  cout << "  BRs    = eta 5e-9, eta' 1.7e-8\n";
  cout << "  sigmaGen from PYTHIA (mb) = " << pythia.info.sigmaGen() << "\n";

  printSummary("eta (221)", etaCounts, nGenerated, 5.0e-9);
  printSummary("eta' (331)", etaPrimeCounts, nGenerated, 1.7e-8);

  return 0;
}
