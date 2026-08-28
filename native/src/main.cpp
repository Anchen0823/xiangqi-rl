#include "xiangqi/position.hpp"
#include "xiangqi/search.hpp"

#include <algorithm>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>

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
        << (position.currentRepetitionCount() >= 3 ? "true" : "false") << "}"
        << ",\"result\":{\"kind\":\"" << resultName(gameResult.kind)
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

} // namespace

int main() {
    xiangqi::Position position;
    xiangqi::PikafishClient search;
    std::string line;
    while (std::getline(std::cin, line)) {
        const std::string id = stringField(line, "id").value_or("");
        const std::string method = stringField(line, "method").value_or("");
        if (method == "newGame") {
            std::string error;
            position.loadFen(xiangqi::Position::InitialFen, &error);
            std::cout << response(id, true, snapshotJson(position)) << std::endl;
        } else if (method == "snapshot" || method == "legalMoves") {
            std::cout << response(id, true, snapshotJson(position)) << std::endl;
        } else if (method == "loadFen") {
            const auto fen = stringField(line, "fen");
            std::string error;
            if (!fen || !position.loadFen(*fen, &error))
                std::cout << response(id, false, "null", error.empty() ? "Missing fen" : error) << std::endl;
            else
                std::cout << response(id, true, snapshotJson(position)) << std::endl;
        } else if (method == "playMove") {
            const auto encoded = stringField(line, "move");
            const auto move = encoded ? xiangqi::Move::fromUcci(*encoded) : std::nullopt;
            std::string error;
            if (!move || !position.play(*move, &error))
                std::cout << response(id, false, "null", error.empty() ? "Invalid move encoding" : error) << std::endl;
            else
                std::cout << response(id, true, snapshotJson(position)) << std::endl;
        } else if (method == "undo") {
            if (!position.undo()) std::cout << response(id, false, "null", "Nothing to undo") << std::endl;
            else std::cout << response(id, true, snapshotJson(position)) << std::endl;
        } else if (method == "analyze") {
            const std::string difficulty = stringField(line, "difficulty").value_or("club");
            const int depth = difficulty == "beginner" ? 4 : difficulty == "casual" ? 7
                : difficulty == "advanced" ? 10 : difficulty == "expert" ? 18 : 14;
            auto searched = search.analyze(position.fen(), depth);
            const auto fallback = position.fallbackBestMove();
            std::ostringstream analysis;
            if (searched) {
                const int sign = position.sideToMove() == xiangqi::Color::Red ? 1 : -1;
                analysis << "{\"depth\":" << searched->depth << ",\"nodes\":" << searched->nodes
                         << ",\"nps\":" << searched->nps << ",\"scoreCp\":" << searched->scoreCp * sign
                         << ",\"mate\":" << (searched->mate ? std::to_string(*searched->mate * sign) : "null")
                         << ",\"backend\":\"" << escapeJson(search.backend()) << "\",\"pv\":";
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
                         << escapeJson(search.status()) << "\",\"pv\":"
                         << (fallback ? "[\"" + fallback->ucci() + "\"]" : "[]") << '}';
            }
            std::cout << response(id, true, analysis.str()) << std::endl;
        } else if (method == "stop") {
            search.stop();
            std::cout << response(id, true, "{\"stopped\":true}") << std::endl;
        } else if (method == "quit") {
            std::cout << response(id, true, "{\"quitting\":true}") << std::endl;
            break;
        } else {
            std::cout << response(id, false, "null", "Unknown method") << std::endl;
        }
    }
    return 0;
}
