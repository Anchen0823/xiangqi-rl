#include "xiangqi/baseline.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <vector>

namespace xiangqi {

namespace {

// Fixed, hard-coded material values mirroring Position::pieceValue.
int materialValue(char piece) {
    switch (std::tolower(static_cast<unsigned char>(piece))) {
        case 'r': return 900;
        case 'c': return 450;
        case 'n': return 400;
        case 'b': return 200;
        case 'a': return 200;
        case 'p': return 100;
        case 'k': return 10000;
        default: return 0;
    }
}

// Piece-square tables from red's perspective. Row = rankIndex (0 = enemy
// back rank, 9 = own back rank; red uses rank directly, black uses 9 - rank),
// column = file. Higher is better for the owner. Values are intentionally
// small so material dominates; they are fixed and never tuned at runtime.
constexpr std::array<std::array<int, 9>, 10> KingPst = {{
    {{0, 0, 0, -4, -8, -4, 0, 0, 0}},
    {{0, 0, 0, -2, -4, -2, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, -2, -4, -2, 0, 0, 0}},
    {{0, 0, 0, -4, -6, -4, 0, 0, 0}},
    {{0, 0, 0, -6, -8, -6, 0, 0, 0}},
    {{0, 0, 0, -8, -10, -8, 0, 0, 0}},
    {{0, 0, 0, 4, 2, 4, 0, 0, 0}},
    {{0, 0, 0, 6, 8, 6, 0, 0, 0}},
    {{0, 0, 0, 4, 6, 4, 0, 0, 0}},
}};

constexpr std::array<std::array<int, 9>, 10> AdvisorPst = {{
    {{0, 0, 0, -6, -8, -6, 0, 0, 0}},
    {{0, 0, 0, -2, -2, -2, 0, 0, 0}},
    {{0, 0, 0, 4, 6, 4, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, -2, -4, -2, 0, 0, 0}},
    {{0, 0, 0, -4, -6, -4, 0, 0, 0}},
    {{0, 0, 0, -6, -8, -6, 0, 0, 0}},
    {{0, 0, 0, -8, -10, -8, 0, 0, 0}},
    {{0, 0, 0, -10, -12, -10, 0, 0, 0}},
    {{0, 0, 0, -12, -14, -12, 0, 0, 0}},
}};

constexpr std::array<std::array<int, 9>, 10> ElephantPst = {{
    {{0, 0, 0, -4, -6, -4, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 2, 4, 6, 4, 2, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 2, 4, 2, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
}};

constexpr std::array<std::array<int, 9>, 10> HorsePst = {{
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 2, 2, 2, 0, 0, 0}},
    {{0, 0, 2, 6, 8, 6, 2, 0, 0}},
    {{0, 2, 6, 10, 12, 10, 6, 2, 0}},
    {{0, 2, 8, 12, 14, 12, 8, 2, 0}},
    {{0, 2, 8, 12, 14, 12, 8, 2, 0}},
    {{0, 2, 6, 10, 12, 10, 6, 2, 0}},
    {{0, 0, 2, 6, 8, 6, 2, 0, 0}},
    {{0, 0, 0, 2, 2, 2, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
}};

constexpr std::array<std::array<int, 9>, 10> RookPst = {{
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 2, 4, 6, 4, 2, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 4, 8, 10, 8, 4, 0, 0}},
    {{0, 0, 4, 8, 10, 8, 4, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 2, 4, 6, 4, 2, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
}};

constexpr std::array<std::array<int, 9>, 10> CannonPst = {{
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 2, 2, 2, 0, 0, 0}},
    {{0, 0, 2, 4, 4, 4, 2, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 4, 6, 8, 6, 4, 0, 0}},
    {{0, 0, 4, 6, 6, 6, 4, 0, 0}},
    {{0, 0, 2, 4, 4, 4, 2, 0, 0}},
    {{0, 0, 0, 2, 2, 2, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
}};

constexpr std::array<std::array<int, 9>, 10> PawnPst = {{
    {{0, 2, 6, 10, 12, 10, 6, 2, 0}},
    {{2, 4, 8, 12, 14, 12, 8, 4, 2}},
    {{2, 4, 8, 12, 14, 12, 8, 4, 2}},
    {{2, 4, 6, 10, 12, 10, 6, 4, 2}},
    {{1, 2, 4, 6, 8, 6, 4, 2, 1}},
    {{0, 0, 2, 4, 6, 4, 2, 0, 0}},
    {{0, 0, 0, 2, 4, 2, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {{0, 0, 0, 0, 0, 0, 0, 0, 0}},
}};

int pst(char piece, int file, int rankIndex) {
    const auto& table = [&]() -> const std::array<std::array<int, 9>, 10>& {
        switch (std::tolower(static_cast<unsigned char>(piece))) {
            case 'k': return KingPst;
            case 'a': return AdvisorPst;
            case 'b': return ElephantPst;
            case 'n': return HorsePst;
            case 'r': return RookPst;
            case 'c': return CannonPst;
            default: return PawnPst;
        }
    }();
    return table[rankIndex][file];
}

// Static evaluation from red's perspective (positive favours red).
int evaluate(const Position& position) {
    int score = 0;
    for (int square = 0; square < 90; ++square) {
        const char piece = position.pieceAt(square);
        if (piece == ' ') continue;
        const bool red = std::isupper(static_cast<unsigned char>(piece)) != 0;
        const int file = square % 9;
        const int rank = square / 9;
        const int rankIndex = red ? rank : 9 - rank;
        const int value = materialValue(piece) + pst(piece, file, rankIndex);
        score += red ? value : -value;
    }
    return score;
}

constexpr int MateScore = 100000;

// Negamax with alpha-beta; returns score from the side-to-move perspective.
int negamax(Position& position, int depth, int alpha, int beta, long long& nodes, int ply) {
    ++nodes;
    const Color stm = position.sideToMove();
    const auto& result = position.result();
    if (result.kind == ResultKind::RedWin || result.kind == ResultKind::BlackWin) {
        // The side to move is always the loser here: the winner's last move
        // flipped the turn. Prefer faster mates by subtracting the ply.
        return -(MateScore - ply);
    }
    if (result.kind == ResultKind::Draw) return 0;
    if (depth <= 0) {
        const int score = evaluate(position);
        return stm == Color::Red ? score : -score;
    }

    std::vector<Move> moves = position.legalMoves();
    if (moves.empty()) {
        // Both checkmate and stalemate (困毙) lose for the side to move.
        return -(MateScore - ply);
    }
    // Deterministic ordering: captures first, by victim value descending,
    // then PST delta descending; ties stay in generation order.
    std::stable_sort(moves.begin(), moves.end(), [&](Move a, Move b) {
        const int va = materialValue(position.pieceAt(a.to)) * 64
            + pst(position.pieceAt(a.to), a.to % 9, a.to / 9);
        const int vb = materialValue(position.pieceAt(b.to)) * 64
            + pst(position.pieceAt(b.to), b.to % 9, b.to / 9);
        return va > vb;
    });

    int best = -2 * MateScore;
    for (const Move move : moves) {
        std::string error;
        if (!position.play(move, &error)) continue;
        const int score = -negamax(position, depth - 1, -beta, -alpha, nodes, ply + 1);
        position.undo();
        if (score > best) best = score;
        if (score > alpha) alpha = score;
        if (alpha >= beta) break;
    }
    return best;
}

} // namespace

std::optional<BaselineResult> baselineSearch(const Position& position, int depth) {
    if (depth <= 0) return std::nullopt;
    Position node = position;
    std::vector<Move> moves = node.legalMoves();
    if (moves.empty()) return std::nullopt;

    std::stable_sort(moves.begin(), moves.end(), [&](Move a, Move b) {
        const int va = materialValue(node.pieceAt(a.to)) * 64
            + pst(node.pieceAt(a.to), a.to % 9, a.to / 9);
        const int vb = materialValue(node.pieceAt(b.to)) * 64
            + pst(node.pieceAt(b.to), b.to % 9, b.to / 9);
        return va > vb;
    });

    Move best = moves.front();
    int bestScore = -2 * MateScore;
    long long nodes = 0;
    const Color stm = node.sideToMove();
    for (const Move move : moves) {
        std::string error;
        if (!node.play(move, &error)) continue;
        const int score = -negamax(node, depth - 1, -2 * MateScore, 2 * MateScore, nodes, 1);
        node.undo();
        if (score > bestScore) {
            bestScore = score;
            best = move;
        }
    }
    // Report from the side-to-move perspective, matching the analyze API.
    const int sign = stm == Color::Red ? 1 : -1;
    return BaselineResult{best, depth, nodes, bestScore * sign};
}

} // namespace xiangqi
