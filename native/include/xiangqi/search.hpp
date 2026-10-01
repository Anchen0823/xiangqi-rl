#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace xiangqi {

struct SearchResult {
    int depth = 0;
    long long nodes = 0;
    long long nps = 0;
    int scoreCp = 0;
    std::optional<int> mate;
    std::vector<std::string> pv;
    std::string bestMove;
};

// Difficulty maps to a node/time budget instead of a fixed ply count, so the
// reached depth becomes a result of the budget and the position rather than a
// hard-coded ceiling. maxDepth stays as a runaway guard.
struct SearchLimits {
    long long nodes = 0;      // 0 means unlimited
    int millis = 0;           // 0 means unlimited
    int maxDepth = 64;        // hard ceiling so a weak network cannot hang the UI
};

// Resolved budgets are non-decreasing across the five difficulty levels.
SearchLimits difficultyLimits(std::string_view difficulty);

// Builds the UCI `go` string. Exposed for testing because the emitted command,
// not the difficulty table, is what actually decides the search.
std::string goCommand(const SearchLimits& limits);

void parseUciInfo(std::string_view line, SearchResult& result);

// Runs while the search waits for engine output and answers true when the
// caller has decided the search should be abandoned. A `stop` sent to Pikafish
// ends the search early, so analyze() still returns the best move found so far.
using AbortCheck = std::function<bool()>;

class PikafishClient {
public:
    PikafishClient();
    ~PikafishClient();
    PikafishClient(const PikafishClient&) = delete;
    PikafishClient& operator=(const PikafishClient&) = delete;

    [[nodiscard]] bool available() const;
    [[nodiscard]] std::string backend() const;
    [[nodiscard]] std::string status() const;
    std::optional<SearchResult> analyze(std::string_view fen, const SearchLimits& limits,
                                        const AbortCheck& shouldAbort = {});
    void stop();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace xiangqi
