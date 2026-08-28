#include "xiangqi/position.hpp"
#include "xiangqi/search.hpp"

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

void testKingAndPawnChaseExceptions() {
    xiangqi::Position position;
    std::string error;
    expect(position.loadFen("4k4/9/n8/9/P3P4/9/9/9/9/4K4 w - - 0 30", &error),
           "direct pawn chase FEN loads");
    expect(position.play(*xiangqi::Move::fromUcci("a5b5"), &error),
           "crossed pawn can move sideways");
    expect(position.history().back().chasedIds.empty(), "pawn's direct chase is allowed");

    expect(position.loadFen("4k4/9/1n7/9/1P2P4/9/9/9/9/1R2K4 w - - 0 30", &error),
           "discovered chase FEN loads");
    expect(position.play(*xiangqi::Move::fromUcci("b5a5"), &error),
           "crossed pawn uncovers rook line");
    expect(!position.history().back().chasedIds.empty(),
           "pawn move causing another piece's new chase is classified as chase");
}

void testRepetitionResponsibilityPriority() {
    using xiangqi::RepetitionResponsibility;
    using xiangqi::ResultKind;
    const auto singleCheck = xiangqi::adjudicateRepetitionCycle(
        RepetitionResponsibility{true, false}, RepetitionResponsibility{}, false);
    expect(singleCheck.kind == ResultKind::BlackWin && singleCheck.reason == "perpetual_check",
           "a sole perpetual checker loses");

    const auto mutualCheck = xiangqi::adjudicateRepetitionCycle(
        RepetitionResponsibility{true, false}, RepetitionResponsibility{true, false}, false);
    expect(mutualCheck.kind == ResultKind::Draw,
           "mutual perpetual check is not assigned by color iteration order");

    const auto soleChase = xiangqi::adjudicateRepetitionCycle(
        RepetitionResponsibility{false, true}, RepetitionResponsibility{}, false);
    expect(soleChase.kind == ResultKind::BlackWin && soleChase.reason == "perpetual_chase",
           "a sole prohibited chaser loses");

    const auto earlyMutual = xiangqi::adjudicateRepetitionCycle(
        RepetitionResponsibility{true, false}, RepetitionResponsibility{true, false}, true);
    expect(earlyMutual.kind == ResultKind::BlackWin
               && earlyMutual.reason == "early_repetition_red_must_deviate",
           "an otherwise drawn early repetition requires red to deviate");
}

void testUciInfoParsing() {
    xiangqi::SearchResult result;
    xiangqi::parseUciInfo("info depth 16 nodes 12345 nps 900000 score cp -37 pv h2e2 h7e7", result);
    expect(result.depth == 16, "UCI depth is parsed");
    expect(result.nodes == 12345 && result.nps == 900000, "UCI node metrics are parsed");
    expect(result.scoreCp == -37 && !result.mate, "UCI centipawn score is parsed");
    expect(result.pv.size() == 2 && result.pv.front() == "h2e2", "UCI principal variation is parsed");
    xiangqi::parseUciInfo("info depth 20 score mate 3 pv e0e1", result);
    expect(result.mate && *result.mate == 3, "UCI mate score is parsed");
}

} // namespace

int main() {
    testInitialPosition();
    testHorseLegAndUndo();
    testFlyingGeneralAndFenValidation();
    testCannonScreen();
    testNaturalLimit();
    testIllegalSelfCheck();
    testKingAndPawnChaseExceptions();
    testRepetitionResponsibilityPriority();
    testUciInfoParsing();
    if (failures) {
        std::cerr << failures << " test(s) failed\n";
        return EXIT_FAILURE;
    }
    std::cout << "All native rule tests passed\n";
    return EXIT_SUCCESS;
}
