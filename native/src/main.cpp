#include "xiangqi/baseline.hpp"
#include "xiangqi/position.hpp"
#include "xiangqi/search.hpp"

#include <algorithm>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>

#ifdef _WIN32
#include <io.h>
#define NOMINMAX
#include <windows.h>
#endif

namespace {

std::string escapeJson(std::string_view value) {
    std::string result;
    result.reserve(value.size() + 8);
    for (char ch : value) {
        switch (ch) {
            case '\\': result += "\\\\"; break;
            case '"': result += "\\\""; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default: result += ch; break;
        }
    }
    return result;
}

std::optional<std::string> stringField(std::string_view json, std::string_view field) {
    const std::string needle = "\"" + std::string(field) + "\"";
    std::size_t at = json.find(needle);
    if (at == std::string_view::npos) return std::nullopt;
    at = json.find(':', at + needle.size());
    if (at == std::string_view::npos) return std::nullopt;
    at = json.find('"', at + 1);
    if (at == std::string_view::npos) return std::nullopt;
    std::string value;
    bool escaped = false;
    for (++at; at < json.size(); ++at) {
        const char ch = json[at];
        if (escaped) {
            if (ch == 'n') value += '\n';
            else if (ch == 'r') value += '\r';
            else if (ch == 't') value += '\t';
            else value += ch;
            escaped = false;
        } else if (ch == '\\') {
            escaped = true;
        } else if (ch == '"') {
            return value;
        } else {
            value += ch;
        }
    }
    return std::nullopt;
}

std::optional<long long> numberField(std::string_view json, std::string_view field) {
    const std::string needle = "\"" + std::string(field) + "\"";
    std::size_t at = json.find(needle);
    if (at == std::string_view::npos) return std::nullopt;
    at = json.find(':', at + needle.size());
    if (at == std::string_view::npos) return std::nullopt;
    ++at;
    while (at < json.size() && std::isspace(static_cast<unsigned char>(json[at]))) ++at;
    std::size_t start = at;
    while (at < json.size() && (std::isdigit(static_cast<unsigned char>(json[at]))
                                || json[at] == '-' || json[at] == '.')) {
        ++at;
    }
    if (at == start) return std::nullopt;
    try {
        return std::stoll(std::string(json.substr(start, at - start)));
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

std::string resultName(xiangqi::ResultKind result) {
    switch (result) {
        case xiangqi::ResultKind::RedWin: return "red_win";
        case xiangqi::ResultKind::BlackWin: return "black_win";
        case xiangqi::ResultKind::Draw: return "draw";
        default: return "ongoing";
    }
}

std::string movesJson(const std::vector<xiangqi::Move>& moves) {
    std::ostringstream out;
    out << '[';
    for (std::size_t i = 0; i < moves.size(); ++i) {
        if (i) out << ',';
        out << '"' << moves[i].ucci() << '"';
    }
    out << ']';
    return out.str();
}

std::string snapshotJson(const xiangqi::Position& position) {
    std::ostringstream history;
    history << '[';
    const auto& records = position.history();
    for (std::size_t i = 0; i < records.size(); ++i) {
        if (i) history << ',';
        const std::string classification = records[i].captured != ' ' ? "capture"
            : records[i].gaveCheck ? "check"
            : !records[i].chasedIds.empty() ? "chase" : "quiet";
        history << "{\"move\":\"" << records[i].move.ucci() << "\",\"check\":"
                << (records[i].gaveCheck ? "true" : "false")
                << ",\"classification\":\"" << classification << "\"}";
    }
    history << ']';

    const auto& gameResult = position.result();
    std::ostringstream out;
    out << "{\"fen\":\"" << escapeJson(position.fen()) << "\",\"sideToMove\":\""
        << (position.sideToMove() == xiangqi::Color::Red ? "red" : "black")
        << "\",\"legalMoves\":" << movesJson(position.legalMoves())
        << ",\"history\":" << history.str() << ",\"noCapturePlies\":"
        << position.noCapturePlies() << ",\"fullmoveNumber\":" << position.fullmoveNumber()
        << ",\"naturalLimit\":{\"plies\":" << position.noCapturePlies()
        << ",\"redChecks\":" << position.checksSinceCapture()[0]
        << ",\"blackChecks\":" << position.checksSinceCapture()[1] << "}"
        << ",\"repetition\":{\"occurrences\":" << position.currentRepetitionCount()
        << ",\"thirdOccurrence\":"
        << (position.currentRepetitionCount() >= 3 ? "true" : "false")
        << "},\"result\":{\"kind\":\"" << resultName(gameResult.kind)
        << "\",\"reason\":\"" << escapeJson(gameResult.reason) << "\"}}";
    return out.str();
}

std::string response(std::string_view id, bool ok, std::string_view payload,
                     std::string_view error = {}) {
    std::ostringstream out;
    out << "{\"id\":\"" << escapeJson(id) << "\",\"ok\":" << (ok ? "true" : "false");
    if (ok) out << ",\"data\":" << payload;
    else out << ",\"error\":\"" << escapeJson(error) << '"';
    out << '}';
    return out.str();
}

// A request that arrived on stdin while a search was running. Its handler runs
// after that search returns, which is why only `stop` may be acted on at once.
struct PendingRequest {
    std::string id;
    std::string line;
};

xiangqi::PikafishClient* searchClient = nullptr;
std::optional<PendingRequest> deferred;

#ifdef _WIN32
// Defined below, next to the internals it needs; analysisJson only forwards it.
bool serviceDeferredRequests();
#endif

void emit(std::string_view id, bool ok, std::string_view payload,
          std::string_view error = {}) {
    std::cout << response(id, ok, payload, error) << std::endl;
}

// Streams the analysis payload for the current position. `apply` mutates the
// position while the search runs, so the caller passes it in rather than this
// helper holding a reference of its own.
std::string analysisJson(const xiangqi::Position& position, std::string_view difficulty,
                         const std::string& requestLine) {
    if (difficulty == "baseline") {
        const auto depthField = numberField(requestLine, "depth");
        const int depth = depthField ? static_cast<int>(*depthField) : 3;
        auto baseline = baselineSearch(position, depth);
        std::ostringstream analysis;
        if (baseline) {
            const int sign = position.sideToMove() == xiangqi::Color::Red ? 1 : -1;
            analysis << "{\"depth\":" << baseline->depth << ",\"nodes\":"
                     << baseline->nodes << ",\"nps\":0,\"scoreCp\":"
                     << baseline->scoreCp * sign
                     << ",\"mate\":null,\"backend\":\"baseline\",\"pv\":[\""
                     << baseline->move.ucci() << "\"]}";
        } else {
            analysis << "{\"depth\":0,\"nodes\":0,\"nps\":0,\"scoreCp\":0,"
                     << "\"mate\":null,\"backend\":\"baseline\",\"pv\":[]}";
        }
        return analysis.str();
    }
    // Difficulty selects a search budget, not a fixed ply count.
#ifdef _WIN32
    auto searched = searchClient->analyze(position.fen(), xiangqi::difficultyLimits(difficulty),
                                          serviceDeferredRequests);
#else
    auto searched = searchClient->analyze(position.fen(), xiangqi::difficultyLimits(difficulty));
#endif
    const auto fallback = position.fallbackBestMove();
    std::ostringstream analysis;
    if (searched) {
        const int sign = position.sideToMove() == xiangqi::Color::Red ? 1 : -1;
        analysis << "{\"depth\":" << searched->depth << ",\"nodes\":" << searched->nodes
                 << ",\"nps\":" << searched->nps << ",\"scoreCp\":" << searched->scoreCp * sign
                 << ",\"mate\":" << (searched->mate ? std::to_string(*searched->mate * sign) : "null")
                 << ",\"backend\":\"" << escapeJson(searchClient->backend()) << "\",\"pv\":";
        analysis << '[';
        for (std::size_t i = 0; i < searched->pv.size(); ++i) {
            if (i) analysis << ',';
            analysis << '\"' << escapeJson(searched->pv[i]) << '\"';
        }
        analysis << "]}";
    } else {
        analysis << "{\"depth\":1,\"nodes\":" << position.legalMoves().size()
                 << ",\"nps\":0,\"scoreCp\":" << position.materialScore()
                 << ",\"mate\":null,\"backend\":\"fallback\",\"status\":\""
                 << escapeJson(searchClient->status()) << "\",\"pv\":"
                 << (fallback ? "[\"" + fallback->ucci() + "\"]" : "[]") << '}';
    }
    return analysis.str();
}

bool applyRequest(xiangqi::Position& position, const std::string& line, bool quit) {
    const std::string id = stringField(line, "id").value_or("");
    const std::string method = stringField(line, "method").value_or("");
    if (method == "newGame") {
        std::string error;
        position.loadFen(xiangqi::Position::InitialFen, &error);
        emit(id, true, snapshotJson(position));
    } else if (method == "snapshot" || method == "legalMoves") {
        emit(id, true, snapshotJson(position));
    } else if (method == "loadFen") {
        const auto fen = stringField(line, "fen");
        std::string error;
        if (!fen || !position.loadFen(*fen, &error))
            emit(id, false, "null", error.empty() ? "Missing fen" : error);
        else
            emit(id, true, snapshotJson(position));
    } else if (method == "playMove") {
        const auto encoded = stringField(line, "move");
        const auto move = encoded ? xiangqi::Move::fromUcci(*encoded) : std::nullopt;
        std::string error;
        if (!move || !position.play(*move, &error))
            emit(id, false, "null", error.empty() ? "Invalid move encoding" : error);
        else
            emit(id, true, snapshotJson(position));
    } else if (method == "undo") {
        if (!position.undo()) emit(id, false, "null", "Nothing to undo");
        else emit(id, true, snapshotJson(position));
    } else if (method == "analyze") {
        const std::string difficulty = stringField(line, "difficulty").value_or("club");
        emit(id, true, analysisJson(position, difficulty, line));
    } else if (method == "stop") {
        searchClient->stop();
        emit(id, true, "{\"stopped\":true}");
    } else if (method == "quit") {
        emit(id, true, "{\"quitting\":true}");
        return true;
    } else {
        emit(id, false, "null", "Unknown method");
    }
    return quit;
}

#ifdef _WIN32
// True when a whole request line is already waiting on stdin. The parent sends
// that pipe, so this must ask the pipe itself: _kbhit() only ever inspects a
// console and reports nothing here, which would leave `stop` unread until the
// search it was meant to cancel had already finished.
bool inputAvailable() {
    const auto handle = reinterpret_cast<HANDLE>(_get_osfhandle(_fileno(stdin)));
    if (handle == INVALID_HANDLE_VALUE) return false;
    DWORD available = 0;
    if (GetFileType(handle) == FILE_TYPE_PIPE) {
        return PeekNamedPipe(handle, nullptr, 0, nullptr, &available, nullptr) && available > 0;
    }
    DWORD mode = 0;
    if (!GetConsoleMode(handle, &mode)) return false;
    DWORD events = 0;
    return GetNumberOfConsoleInputEvents(handle, &events) && events > 0;
}

// Keeps stdin watched while a search owns the thread. Reading a full request
// here would mutate the position mid-search, so the line is parked for the
// outer loop and only `stop` takes effect immediately: it tells the search
// engine to abandon the current `go`, which is what lets a user's move land
// instead of queueing behind the whole analysis budget.
bool serviceDeferredRequests() {
    if (deferred) return false;
    if (!inputAvailable()) return false;
    std::string line;
    if (!std::getline(std::cin, line)) return false;
    const std::string method = stringField(line, "method").value_or("");
    if (method != "stop") {
        deferred = PendingRequest{stringField(line, "id").value_or(""), line};
        return false;
    }
    const std::string id = stringField(line, "id").value_or("");
    searchClient->stop();
    emit(id, true, "{\"stopped\":true}");
    return true;
}
#endif

} // namespace

int main() {
    xiangqi::Position position;
    xiangqi::PikafishClient search;
    searchClient = &search;
    bool quit = false;
    std::string line;
    while (!quit && std::getline(std::cin, line)) {
        quit = applyRequest(position, line, quit);
        if (deferred) {
            auto pending = *deferred;
            deferred.reset();
            quit = applyRequest(position, pending.line, quit);
        }
    }
    return 0;
}
