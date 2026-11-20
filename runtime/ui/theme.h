// The menu's theme library (ui/menu.cpp, ui/option_rows.cpp draw every colour from here).
//
// Two universal themes, the Mario Kart World PC menu's own (mkw-recomp runtime/ui/theme.h): Dark is
// near-black panels with red accents; Light is the Switch 2 system-settings look, light grey panels with a cyan selection.
// A third, the game's own theme, is offered when the running title has one in kGameThemes: its palette and a motif the
// menu draws in the title bar and sidebar (menu.cpp draw_game_motif). A registered game theme is the default until a
// player sets NS2_MENU_THEME; otherwise the default is Dark. NS2_MENU_THEME = dark | light | game.
//
// Adding a game's theme: a Palette below, a row in kGameThemes (its base title ID, the theme's name, the palette, a
// motif), and, for a new motif, a case in menu.cpp draw_game_motif. Colours and simple shapes only: no game artwork.
#pragma once
#include <stdint.h>

#include "imgui.h"

namespace mkw_theme {
enum { THEME_DARK = 0, THEME_LIGHT = 1, THEME_GAME = 2 };
enum { MOTIF_NONE = 0, MOTIF_TENNIS, MOTIF_FUSION, MOTIF_WONDER };

struct Palette {
    ImU32 backdrop, panel, header, sidebar, divider;
    ImU32 text, text_soft, text_dim, text_off;
    ImU32 accent, accent_soft, accent_text;
    ImU32 row_sel, row_hover, warn, help;
    ImU32 button_hover, button_active, scroll;
    bool light;   // ImGui's light base style under it
};

// ---- universal: the Mario Kart World PC menu's Dark and Light
inline constexpr Palette kDark = {
    IM_COL32(0, 0, 0, 175), IM_COL32(24, 24, 28, 255), IM_COL32(32, 32, 38, 255), IM_COL32(17, 17, 21, 255),
    IM_COL32(56, 56, 64, 255), IM_COL32(236, 236, 240, 255), IM_COL32(182, 182, 192, 255), IM_COL32(128, 128, 140, 255),
    IM_COL32(86, 86, 96, 255), IM_COL32(232, 36, 48, 255), IM_COL32(232, 36, 48, 80), IM_COL32(255, 92, 98, 255),
    IM_COL32(44, 44, 52, 255), IM_COL32(40, 40, 47, 200), IM_COL32(255, 156, 64, 255), IM_COL32(30, 30, 36, 255),
    IM_COL32(70, 34, 40, 255), IM_COL32(104, 30, 38, 255), IM_COL32(78, 78, 90, 255), false};
inline constexpr Palette kLight = {
    IM_COL32(0, 0, 0, 150), IM_COL32(240, 240, 242, 255), IM_COL32(250, 250, 251, 255), IM_COL32(228, 228, 232, 255),
    IM_COL32(206, 206, 212, 255), IM_COL32(38, 38, 44, 255), IM_COL32(88, 88, 96, 255), IM_COL32(138, 138, 146, 255),
    IM_COL32(176, 176, 182, 255), IM_COL32(0, 176, 214, 255), IM_COL32(0, 176, 214, 70), IM_COL32(0, 128, 168, 255),
    IM_COL32(255, 255, 255, 255), IM_COL32(255, 255, 255, 150), IM_COL32(206, 92, 20, 255), IM_COL32(250, 250, 251, 255),
    IM_COL32(230, 247, 252, 255), IM_COL32(199, 237, 247, 255), IM_COL32(184, 184, 191, 255), true};

// ---- games
// Mario Tennis Fever, SteelTemple ShadowRacket: championship turf green, court-chalk white, optic tennis-ball yellow-green
inline constexpr Palette kShadowRacket = {
    IM_COL32(5, 14, 8, 172), IM_COL32(18, 36, 24, 255), IM_COL32(12, 26, 17, 255), IM_COL32(14, 30, 20, 255),
    IM_COL32(58, 102, 72, 255), IM_COL32(246, 250, 244, 255), IM_COL32(190, 218, 196, 255), IM_COL32(134, 168, 144, 255),
    IM_COL32(88, 114, 96, 255), IM_COL32(204, 242, 42, 255), IM_COL32(204, 242, 42, 74), IM_COL32(218, 250, 72, 255),
    IM_COL32(30, 62, 41, 255), IM_COL32(24, 48, 33, 210), IM_COL32(255, 168, 60, 255), IM_COL32(13, 27, 18, 255),
    IM_COL32(38, 76, 50, 255), IM_COL32(52, 102, 68, 255), IM_COL32(74, 118, 88, 255), false};
// Fast Fusion, SteelTemple SlowSeparation: midnight indigo, hot-magenta selection, cyan neon (ff-main-reconcile)
inline constexpr Palette kSlowSeparation = {
    IM_COL32(4, 3, 14, 178), IM_COL32(15, 13, 34, 255), IM_COL32(10, 9, 25, 255), IM_COL32(12, 10, 29, 255),
    IM_COL32(52, 46, 96, 255), IM_COL32(246, 244, 255, 255), IM_COL32(192, 186, 226, 255), IM_COL32(132, 126, 176, 255),
    IM_COL32(86, 80, 124, 255), IM_COL32(255, 46, 136, 255), IM_COL32(255, 46, 136, 74), IM_COL32(255, 112, 176, 255),
    IM_COL32(30, 26, 64, 255), IM_COL32(24, 21, 52, 210), IM_COL32(255, 176, 64, 255), IM_COL32(11, 10, 27, 255),
    IM_COL32(60, 26, 72, 255), IM_COL32(92, 30, 92, 255), IM_COL32(84, 74, 140, 255), false};
// Super Mario Bros. Wonder, SteelTemple WonderBloom: bright sky, warm paper, sunshine-yellow selection and flower colours
inline constexpr Palette kWonderBloom = {
    IM_COL32(18, 75, 125, 178), IM_COL32(255, 249, 231, 255), IM_COL32(255, 243, 213, 255), IM_COL32(224, 244, 252, 255),
    IM_COL32(122, 195, 220, 255), IM_COL32(37, 47, 79, 255), IM_COL32(62, 83, 123, 255), IM_COL32(91, 119, 151, 255),
    IM_COL32(137, 157, 177, 255), IM_COL32(255, 205, 42, 255), IM_COL32(255, 205, 42, 86), IM_COL32(55, 43, 57, 255),
    IM_COL32(255, 234, 163, 255), IM_COL32(210, 240, 250, 255), IM_COL32(190, 55, 58, 255), IM_COL32(52, 153, 205, 255),
    IM_COL32(165, 229, 246, 255), IM_COL32(121, 205, 229, 255), IM_COL32(96, 184, 213, 255), true};

struct GameTheme {
    uint64_t title_id;   // the application's base title ID (masked with 0xFFFFFFFFFFFFE000)
    const char *name;    // shown in the menu's theme row
    const Palette *palette;
    int motif;
};
inline constexpr GameTheme kGameThemes[] = {
    {0x0400D4201C6EA000ull, "SteelTemple ShadowRacket", &kShadowRacket, MOTIF_TENNIS},     // Mario Tennis Fever
    {0x040041E0212AE000ull, "SteelTemple SlowSeparation", &kSlowSeparation, MOTIF_FUSION}, // Fast Fusion
    {0x040015100B514000ull, "WonderBloom", &kWonderBloom, MOTIF_WONDER},                  // Super Mario Bros. Wonder
};

// The running title's own theme, or nullptr.
inline const GameTheme *game_theme(uint64_t title_id) {
    for (const GameTheme &g : kGameThemes)
        if (g.title_id == (title_id & 0xFFFFFFFFFFFFE000ull)) return &g;
    return nullptr;
}

inline ImU32 kBackdrop, kPanel, kHeader, kSidebar, kDivider;
inline ImU32 kText, kTextSoft, kTextDim, kTextOff;
inline ImU32 kAccent, kAccentSoft, kAccentText;   // selection outline and arrows; changed values, selected category
inline ImU32 kRowSel, kRowHover, kWarn, kHelp;
inline ImU32 kButtonHover, kButtonActive, kScroll;
inline int kMotif;          // the motif in effect (MOTIF_NONE for Dark and Light)
inline bool kLightBase;     // ImGui's light base style

// theme: THEME_DARK, THEME_LIGHT or THEME_GAME (the title's own; Dark when it has none). Returns the theme in effect.
inline int apply(int theme, uint64_t title_id) {
    const GameTheme *g = theme == THEME_GAME ? game_theme(title_id) : nullptr;
    if (theme == THEME_GAME && !g) theme = THEME_DARK;
    const Palette &p = g ? *g->palette : theme == THEME_LIGHT ? kLight : kDark;
    kBackdrop = p.backdrop, kPanel = p.panel, kHeader = p.header, kSidebar = p.sidebar, kDivider = p.divider;
    kText = p.text, kTextSoft = p.text_soft, kTextDim = p.text_dim, kTextOff = p.text_off;
    kAccent = p.accent, kAccentSoft = p.accent_soft, kAccentText = p.accent_text;
    kRowSel = p.row_sel, kRowHover = p.row_hover, kWarn = p.warn, kHelp = p.help;
    kButtonHover = p.button_hover, kButtonActive = p.button_active, kScroll = p.scroll;
    kMotif = g ? g->motif : MOTIF_NONE;
    kLightBase = p.light;
    return theme;
}

inline ImVec4 v4(ImU32 c) { return ImGui::ColorConvertU32ToFloat4(c); }
}  // namespace mkw_theme
