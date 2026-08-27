#include "xiangqi/search.hpp"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <sstream>
#include <thread>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace xiangqi {

namespace {

std::filesystem::path configuredPath(const char* variable, const std::filesystem::path& fallback) {
    if (const char* value = std::getenv(variable); value && *value) return value;
    return std::filesystem::current_path() / fallback;
}

} // namespace

void parseUciInfo(std::string_view line, SearchResult& result) {
    std::istringstream input{std::string(line)};
    std::string token;
    input >> token;
    if (token != "info") return;
    while (input >> token) {
        if (token == "depth") input >> result.depth;
        else if (token == "nodes") input >> result.nodes;
        else if (token == "nps") input >> result.nps;
        else if (token == "score") {
            std::string kind;
            int value = 0;
            input >> kind >> value;
            if (kind == "cp") { result.scoreCp = value; result.mate.reset(); }
            else if (kind == "mate") result.mate = value;
        } else if (token == "pv") {
            result.pv.clear();
            while (input >> token) result.pv.push_back(token);
            break;
        }
    }
}

struct PikafishClient::Impl {
    std::filesystem::path executable = configuredPath("XIANGQI_PIKAFISH_PATH", "native/bin/pikafish.exe");
    std::filesystem::path network = configuredPath("XIANGQI_NNUE_PATH", "models/champion.nnue");
    std::string message;
#ifdef _WIN32
    HANDLE process = nullptr;
    HANDLE input = nullptr;
    HANDLE output = nullptr;

    bool writeLine(std::string_view line) {
        const std::string command = std::string(line) + "\n";
        DWORD written = 0;
        return input && WriteFile(input, command.data(), static_cast<DWORD>(command.size()), &written, nullptr)
            && written == command.size();
    }

    std::optional<std::string> readLine(std::chrono::milliseconds timeout) {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        std::string line;
        while (std::chrono::steady_clock::now() < deadline) {
            DWORD available = 0;
            if (!PeekNamedPipe(output, nullptr, 0, nullptr, &available, nullptr)) return std::nullopt;
            if (!available) {
                if (WaitForSingleObject(process, 0) == WAIT_OBJECT_0) return std::nullopt;
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
                continue;
            }
            char ch = 0;
            DWORD read = 0;
            if (!ReadFile(output, &ch, 1, &read, nullptr) || !read) return std::nullopt;
            if (ch == '\n') return line;
            if (ch != '\r') line.push_back(ch);
        }
        return std::nullopt;
    }

    bool waitFor(std::string_view expected, std::chrono::seconds timeout) {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (std::chrono::steady_clock::now() < deadline) {
            const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
            auto line = readLine(remaining);
            if (!line) return false;
            if (*line == expected) return true;
        }
        return false;
    }

    bool start() {
        if (!std::filesystem::is_regular_file(executable)) {
            message = "Pikafish executable not installed";
            return false;
        }
        if (!std::filesystem::is_regular_file(network)) {
            message = "Champion NNUE not installed";
            return false;
        }
        SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
        HANDLE childOut = nullptr, childIn = nullptr;
        if (!CreatePipe(&output, &childOut, &attributes, 0)
            || !SetHandleInformation(output, HANDLE_FLAG_INHERIT, 0)
            || !CreatePipe(&childIn, &input, &attributes, 0)
            || !SetHandleInformation(input, HANDLE_FLAG_INHERIT, 0)) {
            message = "Unable to create Pikafish pipes";
            return false;
        }
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
        startup.wShowWindow = SW_HIDE;
        startup.hStdInput = childIn;
        startup.hStdOutput = childOut;
        startup.hStdError = childOut;
        PROCESS_INFORMATION processInfo{};
        std::wstring command = L"\"" + executable.wstring() + L"\"";
        const std::wstring cwd = executable.parent_path().wstring();
        const BOOL created = CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE,
                                            CREATE_NO_WINDOW, nullptr, cwd.c_str(), &startup, &processInfo);
        CloseHandle(childIn); CloseHandle(childOut);
        if (!created) {
            message = "Unable to launch Pikafish";
            return false;
        }
        process = processInfo.hProcess;
        CloseHandle(processInfo.hThread);
        writeLine("uci");
        if (!waitFor("uciok", std::chrono::seconds(10))) { message = "Pikafish UCI handshake failed"; return false; }
        writeLine("setoption name EvalFile value " + network.string());
        writeLine("setoption name Threads value 1");
        writeLine("setoption name Hash value 128");
        writeLine("isready");
        if (!waitFor("readyok", std::chrono::seconds(20))) { message = "Pikafish network load failed"; return false; }
        message = "ready";
        return true;
    }

    void close() {
        if (input) writeLine("quit");
        if (process && WaitForSingleObject(process, 1000) == WAIT_TIMEOUT) TerminateProcess(process, 0);
        if (input) CloseHandle(input);
        if (output) CloseHandle(output);
        if (process) CloseHandle(process);
        input = output = process = nullptr;
    }
#else
    bool start() { message = "Pikafish adapter currently supports Windows builds"; return false; }
    void close() {}
#endif
};

PikafishClient::PikafishClient() : impl_(std::make_unique<Impl>()) { impl_->start(); }
PikafishClient::~PikafishClient() { impl_->close(); }

bool PikafishClient::available() const {
#ifdef _WIN32
    return impl_->process != nullptr && impl_->message == "ready";
#else
    return false;
#endif
}

std::string PikafishClient::status() const { return impl_->message; }

std::optional<SearchResult> PikafishClient::analyze(std::string_view fen, int depth) {
#ifdef _WIN32
    if (!available()) return std::nullopt;
    impl_->writeLine("position fen " + std::string(fen));
    impl_->writeLine("go depth " + std::to_string(std::clamp(depth, 1, 64)));
    SearchResult result;
    while (auto line = impl_->readLine(std::chrono::seconds(60))) {
        if (line->starts_with("info ")) parseUciInfo(*line, result);
        else if (line->starts_with("bestmove ")) {
            std::istringstream best(*line);
            std::string marker;
            best >> marker >> result.bestMove;
            if (result.pv.empty() && !result.bestMove.empty()) result.pv.push_back(result.bestMove);
            return result;
        }
    }
#endif
    return std::nullopt;
}

void PikafishClient::stop() {
#ifdef _WIN32
    if (available()) impl_->writeLine("stop");
#endif
}

} // namespace xiangqi
