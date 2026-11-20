#include "release_update.h"

#include <atomic>
#include <string_view>
#include <tuple>
#include <utility>

#ifdef _WIN32
#include <filesystem>
#include <fstream>
#include <thread>
#include <windows.h>
#include <winhttp.h>
#endif

namespace launcher_release {
namespace {

constexpr size_t MAX_FEED = 512 * 1024;
using View = std::string_view;

constexpr bool space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
constexpr bool digit(char c) { return c >= '0' && c <= '9'; }
constexpr bool alnum(char c) {
    return digit(c) || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

View trim(View text) {
    while (!text.empty() && space(text.front())) text.remove_prefix(1);
    while (!text.empty() && space(text.back())) text.remove_suffix(1);
    return text;
}

bool repository(View slug) {
    size_t slash = slug.find('/');
    if (slash == View::npos || slash < 1 || slash > 39) return false;
    View owner = slug.substr(0, slash), name = slug.substr(slash + 1);
    if (name.empty() || name.size() > 100 || name == "." || name == ".." ||
        !alnum(owner.front()) || !alnum(owner.back())) return false;
    for (char c : owner) if (!alnum(c) && c != '-') return false;
    for (char c : name) if (!alnum(c) && c != '-' && c != '_' && c != '.') return false;
    return true;
}

enum Stage { DEV, ALPHA, BETA, RC, FINAL };
using Version = std::tuple<int, int, int, Stage, int>;

bool take(View &text, View prefix) {
    if (text.substr(0, prefix.size()) != prefix) return false;
    text.remove_prefix(prefix.size());
    return true;
}

bool number(View &text, int &value) {
    if (text.empty() || !digit(text.front())) return false;
    value = 0;
    while (!text.empty() && digit(text.front())) {
        if (value > 99999) return false;
        value = 10 * value + text.front() - '0';
        text.remove_prefix(1);
    }
    return true;
}

bool separator(char c) { return space(c) || c == '-' || c == '_' || c == '.'; }

void skip_separators(View &text) {
    while (!text.empty() && separator(text.front())) text.remove_prefix(1);
}

bool stage_label(View &text, Stage &stage) {
    for (const auto &pair : {std::pair<View, Stage>{"alpha", ALPHA}, {"beta", BETA},
                             {"rc", RC}, {"dev", DEV}}) {
        View rest = text;
        if (take(rest, pair.first) && (rest.empty() || separator(rest.front()) || digit(rest.front()))) {
            text = rest;
            stage = pair.second;
            return true;
        }
    }
    return false;
}

bool version(View text, Version &out) {
    if (text.empty() || text.size() > 96) return false;
    std::string lower(trim(text));
    for (char &c : lower) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    text = lower;
    const size_t metadata = text.find('+');
    if (metadata != View::npos) {
        const View build = text.substr(metadata + 1);
        if (build.empty()) return false;
        for (char c : build) if (!alnum(c) && c != '.' && c != '-') return false;
        text = text.substr(0, metadata);
    }

    Stage stage = FINAL;
    if (stage_label(text, stage)) skip_separators(text);  // "Alpha 0.1.0a"
    take(text, "v");
    int major, minor, patch, revision = 0;
    if (!number(text, major) || !take(text, ".") || !number(text, minor) ||
        !take(text, ".") || !number(text, patch)) return false;

    // A letter on the patch is the release revision, e.g. 0.1.0b follows 0.1.0a.
    if (!text.empty() && text.front() >= 'a' && text.front() <= 'z' &&
        (text.size() == 1 || separator(text[1]))) {
        if (stage == FINAL) stage = ALPHA;
        revision = text.front() - 'a' + 1;
        text.remove_prefix(1);
    }
    if (!text.empty()) {
        skip_separators(text);
        if (!stage_label(text, stage)) return false;
        skip_separators(text);
        if (!text.empty() && !number(text, revision)) return false;
    }
    if (!text.empty()) return false;
    out = {major, minor, patch, stage, revision};
    return true;
}

// Decode only the fields the launcher needs. Bound recursion when skipping author and asset data.
class Json {
public:
    explicit Json(View text) : rest(text) {}

    bool character(char ch) {
        whitespace();
        if (rest.empty() || rest.front() != ch) return false;
        rest.remove_prefix(1);
        return true;
    }

    bool literal(View value) {
        whitespace();
        return take(rest, value);
    }

    bool string(std::string &out) {
        if (!character('"')) return false;
        out.clear();
        while (!rest.empty()) {
            const char ch = rest.front();
            rest.remove_prefix(1);
            if (ch == '"') return true;
            if (static_cast<unsigned char>(ch) < 0x20) return false;
            if (ch != '\\') {
                out += ch;
                continue;
            }
            if (rest.empty()) return false;
            const char escape = rest.front();
            rest.remove_prefix(1);
            switch (escape) {
            case '"': case '\\': case '/': out += escape; break;
            case 'b': out += '\b'; break;
            case 'f': out += '\f'; break;
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            case 'u': {
                unsigned code;
                if (!hex4(code)) return false;
                if (code >= 0xd800 && code <= 0xdbff) {
                    unsigned low;
                    if (!take(rest, "\\u") || !hex4(low) || low < 0xdc00 || low > 0xdfff) return false;
                    code = 0x10000 + ((code - 0xd800) << 10) + low - 0xdc00;
                } else if (code >= 0xdc00 && code <= 0xdfff) {
                    return false;
                }
                utf8(out, code);
                break;
            }
            default: return false;
            }
        }
        return false;
    }

    bool skip(int depth = 0) {
        whitespace();
        if (rest.empty() || depth >= 32) return false;
        std::string ignored;
        if (rest.front() == '"') return string(ignored);
        if (character('{')) {
            if (character('}')) return true;
            do {
                if (!string(ignored) || !character(':') || !skip(depth + 1)) return false;
            } while (character(','));
            return character('}');
        }
        if (character('[')) {
            if (character(']')) return true;
            do {
                if (!skip(depth + 1)) return false;
            } while (character(','));
            return character(']');
        }
        if (literal("true") || literal("false") || literal("null")) return true;
        take(rest, "-");
        if (!take(rest, "0") && !digits()) return false;
        if (take(rest, ".") && !digits()) return false;
        if (take(rest, "e") || take(rest, "E")) {
            if (!take(rest, "+")) take(rest, "-");
            return digits();
        }
        return true;
    }

    bool done() {
        whitespace();
        return rest.empty();
    }

private:
    View rest;

    void whitespace() { while (!rest.empty() && space(rest.front())) rest.remove_prefix(1); }

    bool digits() {
        if (rest.empty() || !digit(rest.front())) return false;
        do { rest.remove_prefix(1); } while (!rest.empty() && digit(rest.front()));
        return true;
    }

    bool hex4(unsigned &out) {
        if (rest.size() < 4) return false;
        out = 0;
        for (char c : rest.substr(0, 4)) {
            unsigned nibble;
            if (digit(c)) nibble = c - '0';
            else if (c >= 'a' && c <= 'f') nibble = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') nibble = c - 'A' + 10;
            else return false;
            out = out * 16 + nibble;
        }
        rest.remove_prefix(4);
        return true;
    }

    static void utf8(std::string &out, unsigned code) {
        if (code <= 0x7f) {
            out += static_cast<char>(code);
            return;
        }
        const int extra = code <= 0x7ff ? 1 : code <= 0xffff ? 2 : 3;
        constexpr unsigned lead[] = {0, 0xc0, 0xe0, 0xf0};
        out += static_cast<char>(lead[extra] | (code >> (6 * extra)));
        for (int i = extra - 1; i >= 0; --i)
            out += static_cast<char>(0x80 | ((code >> (6 * i)) & 0x3f));
    }
};

bool entry(Json &json, std::string &tag, std::string &body, bool &published) {
    published = false;
    if (!json.character('{')) return false;
    if (json.character('}')) return true;
    do {
        std::string key;
        if (!json.string(key) || !json.character(':')) return false;
        if (key == "tag_name") {
            if (!json.string(tag)) return false;
        } else if (key == "body") {
            if (json.literal("null")) body.clear();
            else if (!json.string(body)) return false;
        } else if (key == "draft") {
            if (json.literal("false")) published = true;
            else if (json.literal("true")) published = false;
            else return false;
        } else if (!json.skip()) {
            return false;
        }
    } while (json.character(','));
    return json.character('}');
}

std::string plain_line(View line) {
    // Strip formatting and links and truncate on a UTF-8 boundary.
    constexpr size_t LIMIT = 104;
    std::string plain;
    while (!line.empty() && plain.size() < LIMIT) {
        if (take(line, "https://") || take(line, "http://")) {
            while (!line.empty() && !space(line.front())) line.remove_prefix(1);
            continue;
        }
        if (take(line, "](")) {
            size_t close = line.find(')');
            if (close == View::npos) break;
            line.remove_prefix(close + 1);
            continue;
        }
        const unsigned char ch = line.front();
        if (ch < 0x80) {
            line.remove_prefix(1);
            if (space(static_cast<char>(ch))) {
                if (!plain.empty() && plain.back() != ' ') plain += ' ';
            } else if (ch >= 0x20 && ch != 0x7f && ch != 96 && ch != '*' && ch != '[' &&
                       ch != ']' && ch != '<' && ch != '>' && ch != '@') {
                plain += static_cast<char>(ch);
            }
            continue;
        }
        const size_t width = ch >= 0xc2 && ch <= 0xdf ? 2 :
                             ch >= 0xe0 && ch <= 0xef ? 3 :
                             ch >= 0xf0 && ch <= 0xf4 ? 4 : 0;
        if (!width || line.size() < width) {
            line.remove_prefix(1);
            continue;
        }
        unsigned code = ch & (0x7f >> width);
        bool valid = true;
        for (size_t i = 1; i < width; ++i) {
            const unsigned char next = line[i];
            if ((next & 0xc0) != 0x80) { valid = false; break; }
            code = (code << 6) | (next & 0x3f);
        }
        if (!valid) {
            line.remove_prefix(1);
            continue;
        }
        if (plain.size() + width > LIMIT) break;
        if (code >= (width == 2 ? 0x80u : width == 3 ? 0x800u : 0x10000u) &&
            code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) &&
            !(code >= 0x200b && code <= 0x200f) && !(code >= 0x2028 && code <= 0x202e) &&
            !(code >= 0x2066 && code <= 0x2069)) plain.append(line.substr(0, width));
        line.remove_prefix(width);
    }
    if (!plain.empty() && plain.back() == ' ') plain.pop_back();
    if (!trim(line).empty() && !plain.empty()) plain += "...";
    return plain;
}

std::string summarize(View body) {
    std::string summary;
    bool code_block = false;
    for (int count = 0; count < 3 && !body.empty();) {
        const size_t eol = body.find('\n');
        View line = trim(body.substr(0, eol));
        body = eol == View::npos ? View{} : body.substr(eol + 1);
        if (line.substr(0, 3) == "\x60\x60\x60" || line.substr(0, 3) == "~~~") {
            code_block = !code_block;
            continue;
        }
        if (code_block || line.empty() || line.front() == '#' || line.front() == '|' || line.front() == '<' ||
            line.substr(0, 2) == "![" || line.substr(0, 3) == "---" ||
            line.find("Full Changelog:") != View::npos) continue;
        if (!take(line, "- ") && !take(line, "* ")) take(line, "+ ");
        std::string bullet = plain_line(line);
        if (bullet.empty()) continue;
        if (count++) summary += '\n';
        summary += bullet;
    }
    return summary;
}

std::string tag_path(View tag) {
    constexpr char HEX[] = "0123456789ABCDEF";
    std::string escaped;
    for (const unsigned char ch : tag) {
        if (alnum(ch) || ch == '-' || ch == '_' || ch == '.' || ch == '~') {
            escaped += static_cast<char>(ch);
        } else {
            escaped += '%';
            escaped += HEX[ch >> 4];
            escaped += HEX[ch & 15];
        }
    }
    return escaped;
}

bool select_release(View repo, View installed, View feed, Notice &notice) {
    Version best_version, candidate;
    if (!repository(repo) || !version(installed, best_version) || feed.size() > MAX_FEED) return false;
    Json json(feed);
    if (!json.character('[') || json.character(']')) return false;
    Notice best;
    do {
        std::string tag, body;
        bool published;
        if (!entry(json, tag, body, published)) return false;
        if (published && version(tag, candidate) && best_version < candidate) {
            best_version = candidate;
            best = {tag, summarize(body), "https://github.com/" + std::string(repo) + "/releases/tag/" + tag_path(tag)};
        }
    } while (json.character(','));
    if (!json.character(']') || !json.done() || best.version.empty()) return false;
    notice = std::move(best);
    return true;
}

// The worker publishes an immutable notice that lives until process exit. It never owns SDL
// objects and does not need to be joined when the user presses Play or Quit.
std::atomic<Notice *> found{nullptr};

#ifdef _WIN32
struct WinHttp {
    HMODULE module = LoadLibraryExW(L"winhttp.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);

    template <class T>
    T api(const char *name) const {
        return module ? reinterpret_cast<T>(GetProcAddress(module, name)) : nullptr;
    }

    ~WinHttp() { if (module) FreeLibrary(module); }
};

struct Handle {
    HINTERNET value;
    decltype(&WinHttpCloseHandle) close;
    ~Handle() { if (value) close(value); }
};

std::string fetch(View slug) {
    WinHttp http;
#define LOAD_API(name) const auto name = http.api<decltype(&::name)>(#name)
    LOAD_API(WinHttpOpen);
    LOAD_API(WinHttpCloseHandle);
    LOAD_API(WinHttpSetTimeouts);
    LOAD_API(WinHttpConnect);
    LOAD_API(WinHttpOpenRequest);
    LOAD_API(WinHttpSetOption);
    LOAD_API(WinHttpSendRequest);
    LOAD_API(WinHttpReceiveResponse);
    LOAD_API(WinHttpQueryHeaders);
    LOAD_API(WinHttpReadData);
#undef LOAD_API
    if (!WinHttpOpen || !WinHttpCloseHandle || !WinHttpSetTimeouts || !WinHttpConnect ||
        !WinHttpOpenRequest || !WinHttpSetOption || !WinHttpSendRequest || !WinHttpReceiveResponse ||
        !WinHttpQueryHeaders || !WinHttpReadData) return {};

    Handle session{WinHttpOpen(L"NS2-PC-Launcher", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                               WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0), WinHttpCloseHandle};
    if (!session.value || !WinHttpSetTimeouts(session.value, 2500, 2500, 2500, 3000)) return {};
    Handle connect{WinHttpConnect(session.value, L"api.github.com", INTERNET_DEFAULT_HTTPS_PORT, 0),
                   WinHttpCloseHandle};
    if (!connect.value) return {};
    std::wstring path = L"/repos/" + std::wstring(slug.begin(), slug.end()) + L"/releases?per_page=20";
    Handle request{WinHttpOpenRequest(connect.value, L"GET", path.c_str(), nullptr, WINHTTP_NO_REFERER,
                                      WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE), WinHttpCloseHandle};
    DWORD redirects = WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
    DWORD autologon = WINHTTP_AUTOLOGON_SECURITY_LEVEL_HIGH;
    if (!request.value ||
        !WinHttpSetOption(request.value, WINHTTP_OPTION_REDIRECT_POLICY, &redirects, sizeof redirects) ||
        !WinHttpSetOption(request.value, WINHTTP_OPTION_AUTOLOGON_POLICY, &autologon, sizeof autologon)) return {};
    constexpr wchar_t headers[] = L"Accept: application/vnd.github+json\r\n";
    const auto deadline = GetTickCount64() + 9000;
    if (!WinHttpSendRequest(request.value, headers, static_cast<DWORD>(std::size(headers) - 1),
                            WINHTTP_NO_REQUEST_DATA, 0, 0, 0) ||
        !WinHttpReceiveResponse(request.value, nullptr)) return {};
    DWORD status = 0, length = sizeof status;
    if (!WinHttpQueryHeaders(request.value, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                             WINHTTP_HEADER_NAME_BY_INDEX, &status, &length, WINHTTP_NO_HEADER_INDEX) ||
        status != 200) return {};

    std::string payload;
    char buffer[8192];
    for (;;) {
        DWORD read;
        if (GetTickCount64() > deadline || !WinHttpReadData(request.value, buffer, sizeof buffer, &read) ||
            payload.size() + read > MAX_FEED) return {};
        if (!read) return payload;
        payload.append(buffer, read);
    }
}

void run(std::string exe_dir, std::string installed) {
    try {
#ifdef __cpp_char8_t
        const std::filesystem::path directory(std::u8string(exe_dir.begin(), exe_dir.end()));
#else
        const auto directory = std::filesystem::u8path(exe_dir);
#endif
        std::ifstream file(directory / "ns2-release-repo.txt", std::ios::binary);
        char buffer[144];
        if (!file) return;
        file.read(buffer, sizeof buffer);
        if (!file.eof()) return;
        const View slug = trim(View(buffer, static_cast<size_t>(file.gcount())));
        if (!repository(slug)) return;
        Notice notice;
        if (select_release(slug, installed, fetch(slug), notice))
            found.store(new Notice(std::move(notice)), std::memory_order_release);
    } catch (...) {
        // Update checks are optional, including with invalid or inaccessible local metadata.
    }
}
#endif

} // namespace

void start(const char *exe_dir, const char *port_version) {
#ifdef _WIN32
    static std::atomic<bool> started{false};
    Version ignored;
    if (!exe_dir || !*exe_dir || !port_version || !version(port_version, ignored) || started.exchange(true)) return;
    try {
        std::thread(run, std::string(exe_dir), std::string(port_version)).detach();
    } catch (...) {
        // Leave the launcher usable if the background worker cannot be started.
    }
#else
    (void)exe_dir;
    (void)port_version;
#endif
}

bool available(Notice &notice) {
    const Notice *value = found.load(std::memory_order_acquire);
    if (!value) return false;
    notice = *value;
    return true;
}

bool from_feed(const char *repo, const char *port_version, const char *json, Notice &notice) {
    return repo && port_version && json && select_release(repo, port_version, json, notice);
}

} // namespace launcher_release
