#include "Pythia8/Pythia.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

using namespace Pythia8;

int main(int argc, char* argv[]) {
  if (argc != 3) {
    std::cerr << "Usage: pythia_runner <run.cmnd> <event_summary.json>\n";
    return 2;
  }

  const std::string cmndPath = argv[1];
  const std::string summaryPath = argv[2];

  std::ifstream cmndIn(cmndPath);
  if (!cmndIn.good()) {
    std::cerr << "Input command file not found: " << cmndPath << "\n";
    return 3;
  }

  Pythia pythia;
  pythia.readFile(cmndPath);

  const int nEvent = pythia.mode("Main:numberOfEvents");
  const int nAbort = pythia.mode("Main:timesAllowErrors");

  if (!pythia.init()) {
    std::cerr << "pythia.init() failed\n";
    return 4;
  }

  int attempted = 0;
  int accepted = 0;
  int failures = 0;
  int abortCounter = 0;
  bool abortedByErrors = false;

  for (int iEvent = 0; iEvent < nEvent; ++iEvent) {
    ++attempted;
    if (!pythia.next()) {
      ++failures;
      ++abortCounter;
      if (abortCounter >= nAbort) {
        abortedByErrors = true;
        break;
      }
      continue;
    }

    ++accepted;
  }

  pythia.stat();

  std::ofstream out(summaryPath);
  if (!out.good()) {
    std::cerr << "Failed to write summary file: " << summaryPath << "\n";
    return 5;
  }

  out << "{\n";
  out << "  \"attempted_events\": " << attempted << ",\n";
  out << "  \"accepted_events\": " << accepted << ",\n";
  out << "  \"failed_events\": " << failures << ",\n";
  out << "  \"abort_limit\": " << nAbort << ",\n";
  out << "  \"aborted_by_errors\": " << (abortedByErrors ? "true" : "false") << "\n";
  out << "}\n";
  out.close();

  return abortedByErrors ? 6 : 0;
}
