#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace xiangqi {

enum class Color : std::uint8_t { Red, Black };

inline Color opposite(Color color) {
    return color == Color::Red ? Color::Black : Color::Red;
}

struct Move {
    int from = -1;
    int to = -1;

    [[nodiscard]] bool valid() const { return from >= 0 && from < 90 && to >= 0 && to < 90; }
    [[nodiscard]] std::string ucci() const;
    static std::optional<Move> fromUcci(std::string_view text);
    auto operator<=>(const Move&) const = default;
};

enum class ResultKind : std::uint8_t { Ongoing, RedWin, BlackWin, Draw };

struct Result {
    ResultKind kind = ResultKind::Ongoing;
    std::string reason = "ongoing";
};

struct RepetitionResponsibility {
    bool longCheck = false;
    bool longChase = false;
};

[[nodiscard]] Result adjudicateRepetitionCycle(RepetitionResponsibility red,
                                               RepetitionResponsibility black,
                                               bool earlyDrawRequiresRedDeviation);

struct MoveRecord {
    Move move;
    Color mover = Color::Red;
    char piece = ' ';
    char captured = ' ';
    bool gaveCheck = false;
    std::set<std::uint8_t> chasedIds;
};

class Position {
public:
    static constexpr std::string_view InitialFen =
        "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1";

    Position();

    bool loadFen(std::string_view fen, std::string* error = nullptr);
    [[nodiscard]] std::string fen() const;
    [[nodiscard]] Color sideToMove() const { return side_; }
    [[nodiscard]] const Result& result() const { return result_; }
    [[nodiscard]] int noCapturePlies() const { return noCapturePlies_; }
    [[nodiscard]] int fullmoveNumber() const { return fullmoveNumber_; }
    [[nodiscard]] const std::array<int, 2>& checksSinceCapture() const { return checksSinceCapture_; }
    [[nodiscard]] const std::vector<MoveRecord>& history() const { return records_; }
    [[nodiscard]] int currentRepetitionCount() const;

    [[nodiscard]] std::vector<Move> legalMoves() const;
    [[nodiscard]] std::vector<Move> legalMovesFrom(int square) const;
    bool play(Move move, std::string* error = nullptr);
    bool undo();
    [[nodiscard]] bool inCheck(Color color) const;
    [[nodiscard]] int materialScore() const;
    [[nodiscard]] std::optional<Move> fallbackBestMove() const;
    [[nodiscard]] std::string positionKey() const;

private:
    struct UndoState {
        std::array<char, 90> board{};
        std::array<std::uint8_t, 90> ids{};
        Color side = Color::Red;
        int noCapturePlies = 0;
        std::array<int, 2> checksSinceCapture{};
        int fullmoveNumber = 1;
        Result result;
        std::vector<MoveRecord> records;
        std::vector<std::string> keys;
        std::map<std::string, int> occurrences;
    };

    std::array<char, 90> board_{};
    std::array<std::uint8_t, 90> ids_{};
    Color side_ = Color::Red;
    int noCapturePlies_ = 0;
    std::array<int, 2> checksSinceCapture_{};
    int fullmoveNumber_ = 1;
    Result result_;
    std::vector<MoveRecord> records_;
    std::vector<std::string> keys_;
    std::map<std::string, int> occurrences_;
    std::vector<UndoState> undo_;

    [[nodiscard]] static bool isRed(char piece);
    [[nodiscard]] static bool isBlack(char piece);
    [[nodiscard]] static bool isColor(char piece, Color color);
    [[nodiscard]] static int fileOf(int square) { return square % 9; }
    [[nodiscard]] static int rankOf(int square) { return square / 9; }
    [[nodiscard]] static bool onBoard(int file, int rank) {
        return file >= 0 && file < 9 && rank >= 0 && rank < 10;
    }
    [[nodiscard]] static int squareOf(int file, int rank) { return rank * 9 + file; }
    [[nodiscard]] static int colorIndex(Color color) { return color == Color::Red ? 0 : 1; }

    [[nodiscard]] std::vector<Move> pseudoMoves(Color color) const;
    void appendPieceMoves(int from, std::vector<Move>& moves) const;
    [[nodiscard]] bool attacksSquare(int from, int target) const;
    [[nodiscard]] bool legalAfter(Move move, Color mover) const;
    [[nodiscard]] int kingSquare(Color color) const;
    [[nodiscard]] bool squareAttacked(int square, Color by) const;
    [[nodiscard]] std::set<std::uint8_t> chasedByMove(Move move, Color mover, char captured,
                                                     bool answeredCheck) const;
    [[nodiscard]] bool defended(int square, Color color) const;
    [[nodiscard]] static int pieceValue(char piece);
    void adjudicateRepetition();
    void adjudicateNaturalLimit();
    void updateTerminalByMoves();
    void resetHistoryTracking();
    [[nodiscard]] UndoState snapshot() const;
    void restore(const UndoState& state);
};

} // namespace xiangqi
