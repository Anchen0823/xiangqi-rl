#include "xiangqi/position.hpp"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

int failures = 0;

void expect(bool condition, const std::string& message) {
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

void testInitialPosition() {
    xiangqi::Position position;
    expect(position.fen() == xiangqi::Position::InitialFen, "initial FEN round trip");
    expect(position.legalMoves().size() == 44, "initial position has 44 legal moves");
    expect(!position.inCheck(xiangqi::Color::Red), "red is not initially checked");
    expect(!position.inCheck(xiangqi::Color::Black), "black is not initially checked");
}

void testHorseLegAndUndo() {
    xiangqi::Position position;
    std::string error;
    expect(position.play(*xiangqi::Move::fromUcci("b0c2"), &error), "unblocked horse move is legal");
    expect(position.undo(), "undo succeeds");
    expect(position.fen() == xiangqi::Position::InitialFen, "undo restores exact initial state");
    expect(position.play(*xiangqi::Move::fromUcci("b0a2"), &error), "other horse move is legal");
}

void testFlyingGeneralAndFenValidation() {
    xiangqi::Position position;
    std::string error;
    expect(position.loadFen("4k4/9/9/9/4p4/9/9/9/9/4K4 w - - 0 1", &error),
           "blocking pawn makes kings legal");
    expect(position.inCheck(xiangqi::Color::Red) == false, "blocking pawn prevents flying check");
    expect(!position.loadFen("4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1", &error),
           "facing kings FEN is rejected");
    expect(position.fen() == "4k4/9/9/9/4p4/9/9/9/9/4K4 w - - 0 1",
           "rejected FEN leaves the previous position intact");
}

void testCannonScreen() {
    xiangqi::Position position;
    std::string error;
    expect(position.loadFen("4k4/9/4r4/9/4p4/9/4C4/9/9/3K5 w - - 0 1", &error),
           "cannon test FEN loads");
    const auto capture = xiangqi::Move::fromUcci("e3e7");
    const auto moves = position.legalMoves();
    expect(capture && std::find(moves.begin(), moves.end(), *capture) != moves.end(),
           "cannon captures across exactly one screen");
}

void testNaturalLimit() {
    xiangqi::Position position;
    std::string error;
    expect(position.loadFen("4k4/9/9/9/4P4/9/9/9/3N5/4K4 w - - 119 60", &error),
           "natural-limit FEN loads");
    expect(position.play(*xiangqi::Move::fromUcci("d1f2"), &error), "quiet move reaches limit");
    expect(position.result().kind == xiangqi::ResultKind::Draw, "120 non-capture plies draw");
    expect(position.result().reason == "natural_limit", "natural limit reason is exposed");
}

void testIllegalSelfCheck() {
    xiangqi::Position position;
    std::string error;
    expect(position.loadFen("3k5/9/9/9/4r4/4P4/9/9/9/4K4 w - - 0 1", &error),
           "self-check test FEN loads");
    const auto move = xiangqi::Move::fromUcci("e4d4");
    expect(move && !position.play(*move, &error), "moving the only blocker is illegal");
}

} // namespace

int main() {
    testInitialPosition();
    testHorseLegAndUndo();
    testFlyingGeneralAndFenValidation();
    testCannonScreen();
    testNaturalLimit();
    testIllegalSelfCheck();
    if (failures) {
        std::cerr << failures << " test(s) failed\n";
        return EXIT_FAILURE;
    }
    std::cout << "All native rule tests passed\n";
    return EXIT_SUCCESS;
}
