#pragma once

#include <optional>

#include "xiangqi/position.hpp"

namespace xiangqi {

struct BaselineResult {
    Move move;
    int depth = 0;
    long long nodes = 0;
    int scoreCp = 0;
};

// Deterministic depth-limited alpha-beta search with a fixed material + PST
// evaluation. Hard-coded tables and fixed move ordering make the result fully
// reproducible; the engine never exposes tuning knobs for this baseline.
[[nodiscard]] std::optional<BaselineResult> baselineSearch(const Position& position, int depth);

} // namespace xiangqi
