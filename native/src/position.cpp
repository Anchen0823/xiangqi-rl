#include "xiangqi/position.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <sstream>
#include <tuple>

namespace xiangqi {

namespace {

bool sameColor(char a, char b) {
    return a != ' ' && b != ' ' && (std::isupper(static_cast<unsigned char>(a)) != 0)
        == (std::isupper(static_cast<unsigned char>(b)) != 0);
}

std::string boardKey(const std::array<char, 90>& board, Color side) {
    std::string key(board.begin(), board.end());
    key.push_back(side == Color::Red ? 'w' : 'b');
    return key;
}

} // namespace

std::string Move::ucci() const {
    if (!valid()) return {};
    std::string result(4, '0');
    result[0] = static_cast<char>('a' + from % 9);
    result[1] = static_cast<char>('0' + from / 9);
    result[2] = static_cast<char>('a' + to % 9);
    result[3] = static_cast<char>('0' + to / 9);
    return result;
}

std::optional<Move> Move::fromUcci(std::string_view text) {
    if (text.size() != 4 || text[0] < 'a' || text[0] > 'i' || text[2] < 'a'
        || text[2] > 'i' || text[1] < '0' || text[1] > '9' || text[3] < '0'
        || text[3] > '9') return std::nullopt;
    Move move{(text[1] - '0') * 9 + text[0] - 'a', (text[3] - '0') * 9 + text[2] - 'a'};
    return move.valid() ? std::optional<Move>(move) : std::nullopt;
}

Position::Position() {
    std::string error;
    loadFen(InitialFen, &error);
}

bool Position::isRed(char piece) {
    return piece != ' ' && std::isupper(static_cast<unsigned char>(piece));
}

bool Position::isBlack(char piece) {
    return piece != ' ' && std::islower(static_cast<unsigned char>(piece));
}

bool Position::isColor(char piece, Color color) {
    return color == Color::Red ? isRed(piece) : isBlack(piece);
}

bool Position::loadFen(std::string_view fenText, std::string* error) {
    const UndoState previous = snapshot();
    const auto previousUndo = undo_;
    std::istringstream input{std::string(fenText)};
    std::string placement;
    char active = 'w';
    std::string unused1, unused2;
    int halfmove = 0;
    int fullmove = 1;
    if (!(input >> placement >> active >> unused1 >> unused2 >> halfmove >> fullmove)) {
        if (error) *error = "FEN must contain six fields";
        return false;
    }
    if (active != 'w' && active != 'b') {
        if (error) *error = "FEN active color must be w or b";
        return false;
    }

    std::array<char, 90> nextBoard{};
    nextBoard.fill(' ');
    int fenRank = 9;
    int file = 0;
    int pieceCount = 0;
    constexpr std::string_view validPieces = "RNBACPKrnbacpk";
    for (char token : placement) {
        if (token == '/') {
            if (file != 9 || fenRank == 0) {
                if (error) *error = "Invalid FEN rank width";
                return false;
            }
            --fenRank;
            file = 0;
        } else if (token >= '1' && token <= '9') {
            file += token - '0';
        } else if (validPieces.find(token) != std::string_view::npos) {
            if (file >= 9 || fenRank < 0) {
                if (error) *error = "FEN contains too many squares";
                return false;
            }
            nextBoard[squareOf(file++, fenRank)] = token;
            ++pieceCount;
        } else {
            if (error) *error = "FEN contains an unknown piece";
            return false;
        }
        if (file > 9) {
            if (error) *error = "Invalid FEN rank width";
            return false;
        }
    }
    if (fenRank != 0 || file != 9 || pieceCount > 32) {
        if (error) *error = "FEN does not describe a 9x10 board";
        return false;
    }

    board_ = nextBoard;
    ids_.fill(0);
    std::uint8_t id = 1;
    for (int square = 0; square < 90; ++square) {
        if (board_[square] != ' ') ids_[square] = id++;
    }
    side_ = active == 'w' ? Color::Red : Color::Black;
    noCapturePlies_ = std::clamp(halfmove, 0, 100000);
    checksSinceCapture_ = {0, 0};
    fullmoveNumber_ = std::max(1, fullmove);
    result_ = {};
    records_.clear();
    undo_.clear();
    resetHistoryTracking();

    if (kingSquare(Color::Red) < 0 || kingSquare(Color::Black) < 0) {
        restore(previous);
        undo_ = previousUndo;
        if (error) *error = "FEN must contain both kings";
        return false;
    }
    if (inCheck(opposite(side_))) {
        restore(previous);
        undo_ = previousUndo;
        if (error) *error = "FEN leaves the side that just moved in check";
        return false;
    }
    updateTerminalByMoves();
    return true;
}

std::string Position::fen() const {
    std::ostringstream out;
    for (int rank = 9; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 9; ++file) {
            const char piece = board_[squareOf(file, rank)];
            if (piece == ' ') {
                ++empty;
            } else {
                if (empty) out << empty;
                empty = 0;
                out << piece;
            }
        }
        if (empty) out << empty;
        if (rank) out << '/';
    }
    out << (side_ == Color::Red ? " w " : " b ") << "- - " << noCapturePlies_ << ' '
        << fullmoveNumber_;
    return out.str();
}

std::string Position::positionKey() const {
    return boardKey(board_, side_);
}

int Position::currentRepetitionCount() const {
    const auto found = occurrences_.find(positionKey());
    return found == occurrences_.end() ? 0 : found->second;
}

int Position::kingSquare(Color color) const {
    const char king = color == Color::Red ? 'K' : 'k';
    for (int square = 0; square < 90; ++square) if (board_[square] == king) return square;
    return -1;
}

void Position::appendPieceMoves(int from, std::vector<Move>& moves) const {
    const char piece = board_[from];
    if (piece == ' ') return;
    const Color color = isRed(piece) ? Color::Red : Color::Black;
    const char type = static_cast<char>(std::tolower(static_cast<unsigned char>(piece)));
    const int file = fileOf(from);
    const int rank = rankOf(from);
    auto add = [&](int toFile, int toRank) {
        if (!onBoard(toFile, toRank)) return;
        const int to = squareOf(toFile, toRank);
        if (!isColor(board_[to], color)) moves.push_back({from, to});
    };

    if (type == 'k') {
        const int minRank = color == Color::Red ? 0 : 7;
        const int maxRank = color == Color::Red ? 2 : 9;
        for (const auto [df, dr] : {std::pair{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) {
            const int f = file + df, r = rank + dr;
            if (f >= 3 && f <= 5 && r >= minRank && r <= maxRank) add(f, r);
        }
    } else if (type == 'a') {
        const int minRank = color == Color::Red ? 0 : 7;
        const int maxRank = color == Color::Red ? 2 : 9;
        for (const auto [df, dr] : {std::pair{1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) {
            const int f = file + df, r = rank + dr;
            if (f >= 3 && f <= 5 && r >= minRank && r <= maxRank) add(f, r);
        }
    } else if (type == 'b') {
        for (const auto [df, dr] : {std::pair{2, 2}, {2, -2}, {-2, 2}, {-2, -2}}) {
            const int f = file + df, r = rank + dr;
            if (!onBoard(f, r)) continue;
            if ((color == Color::Red && r > 4) || (color == Color::Black && r < 5)) continue;
            if (board_[squareOf(file + df / 2, rank + dr / 2)] == ' ') add(f, r);
        }
    } else if (type == 'n') {
        constexpr std::array<std::tuple<int, int, int, int>, 8> jumps{{
            {2, 1, 1, 0}, {2, -1, 1, 0}, {-2, 1, -1, 0}, {-2, -1, -1, 0},
            {1, 2, 0, 1}, {-1, 2, 0, 1}, {1, -2, 0, -1}, {-1, -2, 0, -1},
        }};
        for (const auto [df, dr, lf, lr] : jumps) {
            if (onBoard(file + lf, rank + lr)
                && board_[squareOf(file + lf, rank + lr)] == ' ') add(file + df, rank + dr);
        }
    } else if (type == 'r' || type == 'c') {
        for (const auto [df, dr] : {std::pair{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) {
            bool screen = false;
            for (int f = file + df, r = rank + dr; onBoard(f, r); f += df, r += dr) {
                const int to = squareOf(f, r);
                if (type == 'r') {
                    if (board_[to] == ' ') moves.push_back({from, to});
                    else {
                        if (!sameColor(piece, board_[to])) moves.push_back({from, to});
                        break;
                    }
                } else if (!screen) {
                    if (board_[to] == ' ') moves.push_back({from, to});
                    else screen = true;
                } else if (board_[to] != ' ') {
                    if (!sameColor(piece, board_[to])) moves.push_back({from, to});
                    break;
                }
            }
        }
    } else if (type == 'p') {
        const int forward = color == Color::Red ? 1 : -1;
        add(file, rank + forward);
        const bool crossed = color == Color::Red ? rank >= 5 : rank <= 4;
        if (crossed) {
            add(file - 1, rank);
            add(file + 1, rank);
        }
    }
}

std::vector<Move> Position::pseudoMoves(Color color) const {
    std::vector<Move> moves;
    moves.reserve(64);
    for (int square = 0; square < 90; ++square) {
        if (isColor(board_[square], color)) appendPieceMoves(square, moves);
    }
    return moves;
}

bool Position::attacksSquare(int from, int target) const {
    std::vector<Move> moves;
    appendPieceMoves(from, moves);
    return std::ranges::any_of(moves, [target](const Move move) { return move.to == target; });
}

bool Position::squareAttacked(int square, Color by) const {
    for (int from = 0; from < 90; ++from) {
        if (isColor(board_[from], by) && attacksSquare(from, square)) return true;
    }
    const int king = kingSquare(by);
    if (king >= 0 && fileOf(king) == fileOf(square)) {
        bool clear = true;
        const int step = king < square ? 9 : -9;
        for (int at = king + step; at != square; at += step) {
            if (board_[at] != ' ') { clear = false; break; }
        }
        if (clear) return true;
    }
    return false;
}

bool Position::inCheck(Color color) const {
    const int king = kingSquare(color);
    return king < 0 || squareAttacked(king, opposite(color));
}

bool Position::legalAfter(Move move, Color mover) const {
    Position copy = *this;
    copy.undo_.clear();
    const char piece = copy.board_[move.from];
    copy.board_[move.to] = piece;
    copy.board_[move.from] = ' ';
    return !copy.inCheck(mover);
}

std::vector<Move> Position::legalMoves() const {
    if (result_.kind != ResultKind::Ongoing) return {};
    std::vector<Move> result;
    for (Move move : pseudoMoves(side_)) if (legalAfter(move, side_)) result.push_back(move);
    return result;
}

std::vector<Move> Position::legalMovesFrom(int square) const {
    std::vector<Move> result;
    for (Move move : legalMoves()) if (move.from == square) result.push_back(move);
    return result;
}

bool Position::defended(int square, Color color) const {
    for (int from = 0; from < 90; ++from) {
        if (from != square && isColor(board_[from], color) && attacksSquare(from, square)) return true;
    }
    return false;
}

int Position::pieceValue(char piece) {
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

std::set<std::uint8_t> Position::chasedByMove(Move move, Color mover) const {
    std::set<std::uint8_t> chased;
    const char moved = board_[move.to];
    const char type = static_cast<char>(std::tolower(static_cast<unsigned char>(moved)));
    if (type == 'k' || type == 'p') return chased;
    for (int target = 0; target < 90; ++target) {
        const char victim = board_[target];
        if (!isColor(victim, opposite(mover)) || !attacksSquare(move.to, target)) continue;
        if (std::tolower(static_cast<unsigned char>(victim)) == 'p') {
            const int rank = rankOf(target);
            if ((isRed(victim) && rank <= 4) || (isBlack(victim) && rank >= 5)) continue;
        }
        const bool protectedVictim = defended(target, opposite(mover));
        if (protectedVictim && pieceValue(moved) >= pieceValue(victim)) continue;
        chased.insert(ids_[target]);
    }
    return chased;
}

Position::UndoState Position::snapshot() const {
    return {board_, ids_, side_, noCapturePlies_, checksSinceCapture_, fullmoveNumber_, result_,
            records_, keys_, occurrences_};
}

void Position::restore(const UndoState& state) {
    board_ = state.board;
    ids_ = state.ids;
    side_ = state.side;
    noCapturePlies_ = state.noCapturePlies;
    checksSinceCapture_ = state.checksSinceCapture;
    fullmoveNumber_ = state.fullmoveNumber;
    result_ = state.result;
    records_ = state.records;
    keys_ = state.keys;
    occurrences_ = state.occurrences;
}

bool Position::play(Move move, std::string* error) {
    if (result_.kind != ResultKind::Ongoing) {
        if (error) *error = "Game is already over";
        return false;
    }
    const auto legal = legalMoves();
    if (std::ranges::find(legal, move) == legal.end()) {
        if (error) *error = "Illegal move";
        return false;
    }
    undo_.push_back(snapshot());
    const Color mover = side_;
    const char moved = board_[move.from];
    const char captured = board_[move.to];
    const std::uint8_t movedId = ids_[move.from];
    board_[move.to] = moved;
    board_[move.from] = ' ';
    ids_[move.to] = movedId;
    ids_[move.from] = 0;
    side_ = opposite(side_);
    if (captured != ' ') {
        noCapturePlies_ = 0;
        checksSinceCapture_ = {0, 0};
    } else {
        ++noCapturePlies_;
    }
    const bool gaveCheck = inCheck(side_);
    if (gaveCheck) ++checksSinceCapture_[colorIndex(mover)];
    const auto chased = gaveCheck ? std::set<std::uint8_t>{} : chasedByMove(move, mover);
    records_.push_back({move, mover, moved, captured, gaveCheck, chased});
    if (mover == Color::Black) ++fullmoveNumber_;

    const std::string key = positionKey();
    keys_.push_back(key);
    ++occurrences_[key];
    adjudicateRepetition();
    if (result_.kind == ResultKind::Ongoing) adjudicateNaturalLimit();
    if (result_.kind == ResultKind::Ongoing) updateTerminalByMoves();
    return true;
}

bool Position::undo() {
    if (undo_.empty()) return false;
    const UndoState state = std::move(undo_.back());
    undo_.pop_back();
    restore(state);
    return true;
}

void Position::adjudicateNaturalLimit() {
    for (Color claimant : {Color::Red, Color::Black}) {
        const int checks = checksSinceCapture_[colorIndex(claimant)];
        const int effective = noCapturePlies_ - std::max(0, checks - 10);
        if (effective >= 120) {
            result_ = {ResultKind::Draw, "natural_limit"};
            return;
        }
    }
}

void Position::adjudicateRepetition() {
    const std::string key = positionKey();
    if (occurrences_[key] < 3) return;
    std::vector<std::size_t> occurrences;
    for (std::size_t i = 0; i < keys_.size(); ++i) if (keys_[i] == key) occurrences.push_back(i);
    if (occurrences.size() < 3) return;
    const std::size_t beginPosition = occurrences[occurrences.size() - 3];
    const std::size_t beginMove = beginPosition;

    std::array<bool, 2> hasMove{false, false};
    std::array<bool, 2> allCheck{true, true};
    std::array<std::set<std::uint8_t>, 2> chaseIntersection;
    std::array<bool, 2> chaseInitialized{false, false};
    for (std::size_t i = beginMove; i < records_.size(); ++i) {
        const MoveRecord& record = records_[i];
        const int index = colorIndex(record.mover);
        hasMove[index] = true;
        allCheck[index] = allCheck[index] && record.gaveCheck;
        if (!record.gaveCheck) {
            if (!chaseInitialized[index]) {
                chaseIntersection[index] = record.chasedIds;
                chaseInitialized[index] = true;
            } else {
                std::set<std::uint8_t> next;
                std::set_intersection(chaseIntersection[index].begin(), chaseIntersection[index].end(),
                                      record.chasedIds.begin(), record.chasedIds.end(),
                                      std::inserter(next, next.begin()));
                chaseIntersection[index] = std::move(next);
            }
        }
    }

    for (Color color : {Color::Red, Color::Black}) {
        const int index = colorIndex(color);
        if (hasMove[index] && allCheck[index]) {
            result_ = {color == Color::Red ? ResultKind::BlackWin : ResultKind::RedWin,
                       "perpetual_check"};
            return;
        }
    }
    const bool redChase = chaseInitialized[0] && !chaseIntersection[0].empty();
    const bool blackChase = chaseInitialized[1] && !chaseIntersection[1].empty();
    if (redChase != blackChase) {
        result_ = {redChase ? ResultKind::BlackWin : ResultKind::RedWin, "perpetual_chase"};
    } else if (fullmoveNumber_ <= 25) {
        result_ = {ResultKind::BlackWin, "early_repetition_red_must_deviate"};
    } else {
        result_ = {ResultKind::Draw, "mutual_repetition"};
    }
}

void Position::updateTerminalByMoves() {
    if (result_.kind != ResultKind::Ongoing) return;
    const auto moves = legalMoves();
    if (!moves.empty()) return;
    result_ = {side_ == Color::Red ? ResultKind::BlackWin : ResultKind::RedWin,
               inCheck(side_) ? "checkmate" : "stalemate"};
}

void Position::resetHistoryTracking() {
    occurrences_.clear();
    keys_.clear();
    const std::string key = positionKey();
    keys_.push_back(key);
    occurrences_[key] = 1;
}

int Position::materialScore() const {
    int score = 0;
    for (char piece : board_) {
        if (isRed(piece)) score += pieceValue(piece);
        else if (isBlack(piece)) score -= pieceValue(piece);
    }
    return score;
}

std::optional<Move> Position::fallbackBestMove() const {
    const auto moves = legalMoves();
    if (moves.empty()) return std::nullopt;
    return *std::max_element(moves.begin(), moves.end(), [&](Move a, Move b) {
        return pieceValue(board_[a.to]) < pieceValue(board_[b.to]);
    });
}

} // namespace xiangqi
