#pragma once

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

void parseUciInfo(std::string_view line, SearchResult& result);

class PikafishClient {
public:
    PikafishClient();
    ~PikafishClient();
    PikafishClient(const PikafishClient&) = delete;
    PikafishClient& operator=(const PikafishClient&) = delete;

    [[nodiscard]] bool available() const;
    [[nodiscard]] std::string backend() const;
    [[nodiscard]] std::string status() const;
    std::optional<SearchResult> analyze(std::string_view fen, int depth);
    void stop();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace xiangqi
