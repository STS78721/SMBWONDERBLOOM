#pragma once

#include <string>

namespace launcher_release {

struct Notice {
    std::string version;
    std::string summary;
    std::string url;
};

// Starts at most one optional background check. Calling available never waits for the network.
void start(const char *exe_dir, const char *port_version);
bool available(Notice &notice);

// Parses a GitHub releases response, also used by the deterministic launcher screenshot fixture.
bool from_feed(const char *repo, const char *port_version, const char *json, Notice &notice);

} // namespace launcher_release
