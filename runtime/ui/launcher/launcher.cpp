// The optional start screen. Its SDL window and renderer are closed before the guest starts.
#include <SDL3/SDL.h>
#include <ctype.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "backends/imgui_impl_sdl3.h"
#include "backends/imgui_impl_sdlrenderer3.h"
#include "imgui.h"
#include "game_profile.h"
#include "ui/launcher/launcher.h"
#include "ui/launcher/release_update.h"
#include "ui/theme.h"

extern "C" {
#include "cfg.h"
#include "platform/platform.h"
#include "shader_ready.h"
#include "ui_text.h"
void rt_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
extern const char rt_port_version[];
extern const char rt_game_display_version[] __attribute__((weak));
const unsigned char *menu_font_data(int *size);
}

namespace {

enum Page { PAGE_MAIN, PAGE_PROFILE };

struct Palette {
    ImU32 bg, panel, raised, hover, pressed, accent, accent_hot, accent_down;
    ImU32 text, heading, dim, off, focus, line, warn;
    bool dark;
};

struct State {
    SDL_Window *window;
    SDL_Renderer *renderer;
    SDL_Texture *icon;
    SDL_Texture *splash;
    int splash_w, splash_h;
    ImGuiStyle base_style;
    ImFont *font26, *font30, *font36, *font60;
    float scale;
    Palette colors;
    Page page;
    int result;
    long shot_at;
    bool shot_mode;
    bool shot_motion;
    bool fonts_ready;
    bool sdl_backend_ready;
    bool renderer_backend_ready;
    bool shown;
    bool profile_ready;
    bool shaders_ready;
    double intro_at;
    float motion_time;
    const char *exefs;
    const char *romfs;
    char name[33];
    char exe_dir[PLAT_PATH_MAX * 2];
    const char *profile_note;
    ImU32 profile_note_color;
    launcher_release::Notice update;
} L = {};

static ImU32 rgba(int r, int g, int b, int a = 255) { return IM_COL32(r, g, b, a); }

static ImU32 with_alpha(ImU32 c, float a) {
    unsigned alpha = (unsigned)(((c >> IM_COL32_A_SHIFT) & 0xFF) * fmaxf(0.0f, fminf(1.0f, a)));
    return (c & ~IM_COL32_A_MASK) | (alpha << IM_COL32_A_SHIFT);
}

static ImVec4 v4(ImU32 c) { return ImGui::ColorConvertU32ToFloat4(c); }

static int theme_kind(void) {
    const char *value = cfg_value("NS2_MENU_THEME");
    if (!cfg_is_set("NS2_MENU_THEME") && mkw_theme::game_theme(game_profile()->title_id))
        return mkw_theme::THEME_GAME;
    if (!strcmp(value, "light")) return mkw_theme::THEME_LIGHT;
    if (!strcmp(value, "game") && mkw_theme::game_theme(game_profile()->title_id)) return mkw_theme::THEME_GAME;
    return mkw_theme::THEME_DARK;
}

static void palette_init(void) {
    int theme = mkw_theme::apply(theme_kind(), game_profile()->title_id);
    if (theme == mkw_theme::THEME_DARK) {
        // Dark palette from MKW's launcher_look.cpp:look_palette.
        L.colors = {rgba(14, 14, 17), rgba(22, 22, 26), rgba(38, 38, 45), rgba(56, 40, 46),
                    rgba(74, 44, 52), rgba(200, 28, 40), rgba(226, 44, 56), rgba(170, 22, 32),
                    rgba(238, 238, 242), rgba(186, 186, 196), rgba(150, 150, 162), rgba(86, 86, 96),
                    rgba(255, 255, 255, 235), rgba(255, 255, 255, 24), rgba(236, 160, 70), true};
    } else if (theme == mkw_theme::THEME_LIGHT) {
        // Light palette from MKW's launcher_look.cpp:look_palette.
        L.colors = {rgba(232, 232, 236), rgba(244, 244, 246), rgba(255, 255, 255), rgba(230, 247, 252),
                    rgba(199, 237, 247), rgba(0, 128, 168), rgba(0, 146, 188), rgba(0, 110, 146),
                    rgba(38, 38, 44), rgba(88, 88, 96), rgba(104, 104, 112), rgba(176, 176, 182),
                    rgba(0, 176, 214), rgba(0, 0, 0, 28), rgba(196, 110, 20), false};
    } else {
        const mkw_theme::Palette &p = *mkw_theme::game_theme(game_profile()->title_id)->palette;
        L.colors = {p.sidebar, p.panel, p.row_sel, p.button_hover, p.button_active, p.accent,
                    p.accent, p.button_active, p.text, p.text_soft, p.text_dim, p.text_off,
                    p.accent, p.divider, p.warn, !p.light};
    }
}

static ImU32 accent_text(void) {
    ImVec4 c = v4(L.colors.accent);
    float luminance = 0.299f * c.x + 0.587f * c.y + 0.114f * c.z;
    return luminance > 0.55f ? rgba(34, 25, 0) : rgba(255, 255, 255);
}

static void style_init(void) {
    palette_init();
    if (L.colors.dark) ImGui::StyleColorsDark(&L.base_style);
    else ImGui::StyleColorsLight(&L.base_style);
    ImGuiStyle &s = L.base_style;
    s.WindowRounding = 4; s.FrameRounding = 4; s.GrabRounding = 4; s.ChildRounding = 6; s.PopupRounding = 6;
    s.WindowPadding = ImVec2(28, 22); s.FramePadding = ImVec2(16, 9); s.ItemSpacing = ImVec2(12, 10);
    s.WindowBorderSize = 0; s.FrameBorderSize = 0; s.PopupBorderSize = 1; s.ScrollbarSize = 12;
    ImVec4 *c = s.Colors;
    c[ImGuiCol_WindowBg] = v4(L.colors.panel);
    c[ImGuiCol_ChildBg] = ImVec4(0, 0, 0, 0);
    c[ImGuiCol_PopupBg] = v4(L.colors.panel);
    c[ImGuiCol_Border] = v4(L.colors.line);
    c[ImGuiCol_Text] = v4(L.colors.text);
    c[ImGuiCol_TextDisabled] = v4(L.colors.dim);
    c[ImGuiCol_TextSelectedBg] = v4(with_alpha(L.colors.accent, 0.42f));
    c[ImGuiCol_FrameBg] = v4(L.colors.raised);
    c[ImGuiCol_FrameBgHovered] = v4(L.colors.hover);
    c[ImGuiCol_FrameBgActive] = v4(L.colors.pressed);
    c[ImGuiCol_Button] = v4(L.colors.raised);
    c[ImGuiCol_ButtonHovered] = v4(L.colors.hover);
    c[ImGuiCol_ButtonActive] = v4(L.colors.pressed);
    c[ImGuiCol_Header] = v4(L.colors.raised);
    c[ImGuiCol_HeaderHovered] = v4(L.colors.hover);
    c[ImGuiCol_HeaderActive] = v4(L.colors.pressed);
    c[ImGuiCol_NavCursor] = v4(L.colors.focus);
    c[ImGuiCol_Separator] = v4(L.colors.line);
    c[ImGuiCol_ScrollbarBg] = ImVec4(0, 0, 0, 0);
    c[ImGuiCol_ScrollbarGrab] = v4(L.colors.hover);
    c[ImGuiCol_ScrollbarGrabHovered] = v4(L.colors.pressed);
    c[ImGuiCol_ScrollbarGrabActive] = v4(L.colors.accent);
    c[ImGuiCol_ModalWindowDimBg] = ImVec4(0, 0, 0, L.colors.dark ? 0.60f : 0.30f);
}

static void fonts_rebuild(float scale) {
    ImGuiIO &io = ImGui::GetIO();
    if (L.fonts_ready) ImGui_ImplSDLRenderer3_DestroyFontsTexture();
    io.Fonts->Clear();
    int bytes = 0;
    const unsigned char *data = menu_font_data(&bytes);
    if (!data || bytes <= 0) return;
    ImFontConfig config;
    config.FontDataOwnedByAtlas = false;
    L.font26 = io.Fonts->AddFontFromMemoryTTF((void *)data, bytes, 26.0f * scale, &config);
    L.font30 = io.Fonts->AddFontFromMemoryTTF((void *)data, bytes, 30.0f * scale, &config);
    L.font36 = io.Fonts->AddFontFromMemoryTTF((void *)data, bytes, 36.0f * scale, &config);
    L.font60 = io.Fonts->AddFontFromMemoryTTF((void *)data, bytes, 60.0f * scale, &config);
    L.fonts_ready = ImGui_ImplSDLRenderer3_CreateFontsTexture();
    if (!L.fonts_ready) rt_log("launcher: could not create the font texture: %s", SDL_GetError());
}

static void restyle(float scale, bool force = false) {
    if (!force && fabsf(L.scale - scale) < 0.001f && L.fonts_ready) return;
    ImGui::GetStyle() = L.base_style;
    ImGui::GetStyle().ScaleAllSizes(scale);
    fonts_rebuild(scale);
    L.scale = scale;
}

static void exe_dir(char *out, size_t cap) {
    out[0] = 0;
    if (!plat_exe_path(out, cap)) return;
    char *cut = plat_last_sep(out);
    if (cut) *cut = 0;
}

static bool path_exists(const char *path) {
    return path && (plat_dir_exists(path) || plat_file_exists(path));
}

static void load_images(void) {
    char path[PLAT_PATH_MAX * 2];
    if (L.exe_dir[0]) {
        snprintf(path, sizeof path, "%s/launcher_icon.png", L.exe_dir);
        if (plat_file_exists(path)) {
            SDL_Surface *surface = SDL_LoadPNG(path);
            if (!surface) rt_log("launcher: could not load %s: %s", path, SDL_GetError());
            else {
                L.icon = SDL_CreateTextureFromSurface(L.renderer, surface);
                if (!L.icon) rt_log("launcher: could not create the cover-art texture: %s", SDL_GetError());
                SDL_DestroySurface(surface);
            }
        } else {
            rt_log("launcher: cover art is unavailable beside the executable: %s", path);
        }
        if (L.icon) SDL_SetTextureScaleMode(L.icon, SDL_SCALEMODE_LINEAR);
    }
    if (L.exe_dir[0]) {
        snprintf(path, sizeof path, "%s/splash.png", L.exe_dir);
        if (plat_file_exists(path)) {
            SDL_Surface *surface = SDL_LoadPNG(path);
            if (surface) {
                L.splash_w = surface->w;
                L.splash_h = surface->h;
                L.splash = SDL_CreateTextureFromSurface(L.renderer, surface);
                SDL_DestroySurface(surface);
            }
            if (L.splash) SDL_SetTextureScaleMode(L.splash, SDL_SCALEMODE_LINEAR);
        }
    }
}

static void free_images(void) {
    if (L.icon) SDL_DestroyTexture(L.icon);
    if (L.splash) SDL_DestroyTexture(L.splash);
    L.icon = L.splash = nullptr;
}

static bool parse_size(int *w, int *h) {
    const char *value = getenv("NS2_LAUNCHER_SIZE");
    int width = 0, height = 0;
    if (!value || sscanf(value, "%dx%d", &width, &height) != 2 || width < 640 || height < 480) return false;
    *w = width;
    *h = height;
    return true;
}

static bool open_window(void) {
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        rt_log("launcher: SDL_Init failed: %s", SDL_GetError());
        return false;
    }
    int width = 1280, height = 720;
    bool fixed_size = parse_size(&width, &height);
    float ds = fixed_size ? 1.0f : SDL_GetDisplayContentScale(SDL_GetPrimaryDisplay());
    if (!(ds > 0)) ds = 1.0f;
    SDL_WindowFlags flags = SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIDDEN;
    if (!fixed_size) flags |= SDL_WINDOW_HIGH_PIXEL_DENSITY;
    L.window = SDL_CreateWindow(game_profile()->display_name, (int)(width * ds), (int)(height * ds), flags);
    L.renderer = L.window ? SDL_CreateRenderer(L.window, nullptr) : nullptr;
    if (!L.renderer) {
        rt_log("launcher: could not create a window and renderer: %s", SDL_GetError());
        if (L.window) SDL_DestroyWindow(L.window);
        L.window = nullptr;
        SDL_Quit();
        return false;
    }
    if (!SDL_SetRenderVSync(L.renderer, 1)) rt_log("launcher: vsync is unavailable: %s", SDL_GetError());
    SDL_SetWindowMinimumSize(L.window, (int)(960 * ds), (int)(540 * ds));
    if (cfg_bool("NS2_FULLSCREEN")) SDL_SetWindowFullscreen(L.window, true);
    return true;
}

static float ease_out(float p) {
    p = fmaxf(0.0f, fminf(1.0f, p));
    return 1.0f - (1.0f - p) * (1.0f - p) * (1.0f - p);
}

static void intro_apply(ImDrawList *draw, int first, float progress, float scale) {
    if (progress >= 1.0f) return;
    float dy = (1.0f - progress) * 12.0f * scale;
    for (int i = first; i < draw->VtxBuffer.Size; ++i) {
        ImDrawVert &vertex = draw->VtxBuffer[i];
        vertex.pos.y += dy;
        unsigned a = (vertex.col >> IM_COL32_A_SHIFT) & 0xFF;
        vertex.col = (vertex.col & ~IM_COL32_A_MASK) | ((unsigned)(a * progress) << IM_COL32_A_SHIFT);
    }
}

static void add_bloom(ImDrawList *draw, ImVec2 center, float radius, float angle, ImU32 color) {
    for (int i = 0; i < 5; ++i) {
        float a = angle + (float)i * 6.283185307f / 5.0f;
        ImVec2 petal(center.x + cosf(a) * radius * 0.42f, center.y + sinf(a) * radius * 0.42f);
        draw->AddCircleFilled(petal, radius * 0.34f, color, 20);
    }
    draw->AddCircleFilled(center, radius * 0.17f, with_alpha(L.colors.accent, 0.72f), 16);
}

static void add_sparkle(ImDrawList *draw, ImVec2 c, float r, ImU32 color) {
    ImVec2 p[] = {ImVec2(c.x, c.y - r), ImVec2(c.x + r * 0.24f, c.y - r * 0.24f),
                  ImVec2(c.x + r, c.y), ImVec2(c.x + r * 0.24f, c.y + r * 0.24f),
                  ImVec2(c.x, c.y + r), ImVec2(c.x - r * 0.24f, c.y + r * 0.24f),
                  ImVec2(c.x - r, c.y), ImVec2(c.x - r * 0.24f, c.y - r * 0.24f)};
    draw->AddConvexPolyFilled(p, 8, color);
}

static void draw_cloud(ImDrawList *draw, ImVec2 c, float s, ImU32 color) {
    draw->AddCircleFilled(ImVec2(c.x - 20 * s, c.y + 1 * s), 16 * s, color, 24);
    draw->AddCircleFilled(ImVec2(c.x, c.y - 8 * s), 22 * s, color, 24);
    draw->AddCircleFilled(ImVec2(c.x + 22 * s, c.y + 2 * s), 15 * s, color, 24);
    draw->AddRectFilled(ImVec2(c.x - 24 * s, c.y), ImVec2(c.x + 25 * s, c.y + 13 * s), color, 6 * s);
}

static void wonder_backdrop(ImDrawList *draw, float w, float h) {
    ImU32 sky_top = rgba(71, 190, 245), sky_low = rgba(151, 229, 249);
    draw->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(w, h), sky_top, rgba(101, 211, 248),
                                  sky_low, rgba(130, 222, 249));

    // A warm sun halo gives the cover card a bright focal point without obscuring its artwork.
    ImVec2 sun(w * 0.82f, h * 0.22f);
    for (int i = 7; i >= 0; --i)
        draw->AddCircleFilled(sun, h * (0.07f + i * 0.034f), rgba(255, 222, 109, 8 + (7 - i) * 2), 64);
    draw->AddCircleFilled(sun, h * 0.065f, rgba(255, 241, 162, 190), 64);

    // Puffy clouds drift slowly above the menu. All art is vector primitives owned by the UI.
    const float t = L.motion_time;
    const ImU32 cloud = rgba(255, 255, 255, 228);
    draw_cloud(draw, ImVec2(w * 0.60f + sinf(t * 0.16f) * 15, h * 0.15f), h * 0.82f / 720.0f, cloud);
    draw_cloud(draw, ImVec2(w * 0.95f + sinf(t * 0.12f + 1.4f) * 20, h * 0.29f), h * 0.72f / 720.0f,
               rgba(255, 255, 255, 206));

    // Rolling green hills ground the scene; the large icon card is drawn above them.
    draw->AddCircleFilled(ImVec2(w * 0.70f, h * 1.13f), h * 0.39f, rgba(79, 192, 105), 72);
    draw->AddCircleFilled(ImVec2(w * 1.00f, h * 1.15f), h * 0.44f, rgba(39, 169, 111), 72);
    draw->AddCircleFilled(ImVec2(w * 0.91f, h * 1.24f), h * 0.30f, rgba(123, 214, 91), 72);

    const ImU32 petals[] = {rgba(255, 205, 42), rgba(53, 153, 205), rgba(236, 89, 85),
                            rgba(162, 112, 220), rgba(70, 174, 111)};
    for (int i = 0; i < 14; ++i) {
        float u = fmodf(i * 0.6180339f, 1.0f);
        float x = w * (0.45f + 0.53f * u) + sinf(t * (0.19f + 0.01f * (i % 4)) + i) * h * 0.022f;
        float y = h * (0.09f + 0.70f * fmodf(i * 0.381966f, 1.0f)) + sinf(t * 0.62f + i * 1.7f) * h * 0.025f;
        float r = h * (0.036f + 0.012f * (i % 3));
        float alpha = 0.76f + 0.18f * (0.5f + 0.5f * sinf(t * 1.1f + i));
        add_bloom(draw, ImVec2(x, y), r, t * (i % 2 ? -0.20f : 0.17f) + i * 0.41f,
                  with_alpha(petals[i % 5], alpha));
    }
    for (int i = 0; i < 30; ++i) {
        float x = w * (0.42f + 0.56f * fmodf(i * 0.6180339f, 1.0f));
        float y = h * (0.03f + 0.86f * fmodf(i * 0.381966f, 1.0f));
        float pulse = 0.35f + 0.65f * (0.5f + 0.5f * sinf(t * 1.8f + i * 1.7f));
        add_sparkle(draw, ImVec2(x, y), h * (0.009f + 0.010f * pulse),
                    with_alpha(petals[(i + 2) % 5], 0.52f + 0.42f * pulse));
    }
}

static void backdrop_draw(ImDrawList *draw, float w, float h) {
    if (L.splash && L.splash_w > 0 && L.splash_h > 0) {
        draw->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), L.colors.bg);
        float k = fmaxf(w / L.splash_w, h / L.splash_h);
        float sw = L.splash_w * k, sh = L.splash_h * k;
        draw->AddImage((ImTextureID)(intptr_t)L.splash, ImVec2((w - sw) * 0.5f, (h - sh) * 0.5f),
                       ImVec2((w + sw) * 0.5f, (h + sh) * 0.5f));
        ImU32 dark = with_alpha(L.colors.bg, 0.90f), none = with_alpha(L.colors.bg, 0.0f);
        draw->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(w * 0.70f, h), dark, none, none, dark);
        draw->AddRectFilledMultiColor(ImVec2(0, h * 0.72f), ImVec2(w, h), none, none, dark, dark);
    } else if (mkw_theme::kMotif == mkw_theme::MOTIF_WONDER) {
        wonder_backdrop(draw, w, h);
    } else {
        draw->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), L.colors.bg);
        for (int i = 7; i >= 0; --i) {
            float r = (0.12f + 0.06f * i) * h;
            draw->AddCircleFilled(ImVec2(w * 0.78f, h * 0.45f), r,
                                  with_alpha(L.colors.accent, 0.018f + 0.006f * (7 - i)), 64);
        }
        for (int i = 0; i < 36; ++i) {
            float x = w * fmodf(i * 0.6180339f, 1.0f);
            float base_y = h * fmodf(i * 0.381966f, 1.0f);
            float y = base_y + sinf(L.motion_time * 0.20f + i) * h * 0.015f;
            draw->AddCircleFilled(ImVec2(x, y), h * (0.0025f + 0.0015f * (i % 3)), with_alpha(L.colors.heading, 0.13f), 12);
        }
    }
    // The main column and the status line stay legible over a user's optional splash image.
    ImU32 fade = with_alpha(L.colors.bg, 0.96f), clear = with_alpha(L.colors.bg, 0.0f);
    draw->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(w * 0.68f, h), fade, clear, clear, fade);
    draw->AddRectFilledMultiColor(ImVec2(0, h * 0.72f), ImVec2(w, h), clear, clear, fade, fade);
}

static void draw_card(ImDrawList *draw, float w, float h) {
    float s = L.scale;
    float size = fminf(h * 0.46f, 500.0f * s);
    if (!L.update.version.empty()) size = fminf(size, w * 0.40f);
    float x = w - fmaxf(50.0f * s, 72.0f * s) - size;
    float y = (L.update.version.empty() ? (h - size) * 0.48f : h * 0.13f)
            + sinf(L.motion_time * 0.75f) * 8.0f * s;
    ImVec2 a(x, y), b(x + size, y + size);
    draw->AddRectFilled(ImVec2(a.x + 4 * s, a.y + 14 * s), ImVec2(b.x + 4 * s, b.y + 14 * s),
                        rgba(0, 0, 0, 90), 28 * s);
    draw->AddRectFilled(a, b, L.colors.panel, 26 * s);
    if (L.icon) {
        draw->AddImageRounded((ImTextureID)(intptr_t)L.icon, a, b, ImVec2(0, 0), ImVec2(1, 1),
                              IM_COL32_WHITE, 24 * s, ImDrawFlags_RoundCornersAll);
    } else {
        add_bloom(draw, ImVec2(a.x + size * 0.5f, a.y + size * 0.5f), size * 0.28f, L.motion_time * 0.08f,
                  with_alpha(L.colors.accent, 0.55f));
    }
    draw->AddRect(a, b, with_alpha(L.colors.line, 0.90f), 26 * s, ImDrawFlags_RoundCornersAll, 1.5f * s);
}

static bool button(const char *id, const char *label, ImVec2 size, bool accent = false, bool play_mark = false) {
    ImVec2 a = ImGui::GetCursorScreenPos(), b(a.x + size.x, a.y + size.y);
    bool hit = ImGui::InvisibleButton(id, size);
    bool hot = ImGui::IsItemHovered() || (ImGui::IsItemFocused() && ImGui::GetIO().NavVisible);
    bool held = ImGui::IsItemActive();
    float s = L.scale;
    ImU32 fill = accent ? (held ? L.colors.accent_down : hot ? L.colors.accent_hot : L.colors.accent)
                        : (held ? L.colors.pressed : hot ? L.colors.hover : L.colors.raised);
    ImDrawList *draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(a, b, fill, 5 * s);
    if (hot) draw->AddRect(a, b, L.colors.focus, 5 * s, ImDrawFlags_RoundCornersAll, 1.5f * s);
    ImFont *font = accent ? L.font36 : L.font30;
    ImU32 text = accent ? accent_text() : L.colors.text;
    ImVec2 ts = font->CalcTextSizeA(font->FontSize, FLT_MAX, 0, label);
    draw->AddText(font, font->FontSize, ImVec2((a.x + b.x - ts.x) * 0.5f, (a.y + b.y - ts.y) * 0.5f), text, label);
    if (play_mark) {
        float k = font->FontSize * 0.20f, cx = a.x + 28 * s, cy = (a.y + b.y) * 0.5f;
        draw->AddTriangleFilled(ImVec2(cx - k * 0.35f, cy - k), ImVec2(cx + k, cy), ImVec2(cx - k * 0.35f, cy + k), text);
    }
    return hit;
}

static bool menu_item(const char *id, const char *label, const char *value, float width) {
    float s = L.scale, height = fmaxf(44.0f * s, 60.0f * s);
    ImVec2 a = ImGui::GetCursorScreenPos(), b(a.x + width, a.y + height);
    ImGui::PushID(id);
    bool hit = ImGui::InvisibleButton("##row", ImVec2(width, height));
    bool hot = ImGui::IsItemHovered() || (ImGui::IsItemFocused() && ImGui::GetIO().NavVisible);
    bool held = ImGui::IsItemActive();
    ImGui::PopID();
    if (hot) {
        ImU32 tint = with_alpha(held ? L.colors.pressed : L.colors.accent, 0.15f);
        ImU32 clear = with_alpha(tint, 0);
        ImGui::GetWindowDrawList()->AddRectFilledMultiColor(a, b, tint, clear, clear, tint);
        ImGui::GetWindowDrawList()->AddRectFilled(a, ImVec2(a.x + 3 * s, b.y), L.colors.accent);
    }
    ImDrawList *draw = ImGui::GetWindowDrawList();
    ImFont *font = L.font30;
    ImU32 color = hot ? L.colors.text : L.colors.heading;
    draw->AddText(font, font->FontSize, ImVec2(a.x + 18 * s + (hot ? 3 * s : 0), (a.y + b.y - font->FontSize) * 0.5f), color, label);
    if (value && *value) {
        ImVec2 vsize = font->CalcTextSizeA(font->FontSize, FLT_MAX, 0, value);
        draw->AddText(font, font->FontSize, ImVec2(b.x - 18 * s - vsize.x, (a.y + b.y - font->FontSize) * 0.5f), color, value);
    }
    return hit;
}

static const char *theme_name(void) {
    int t = theme_kind();
    if (t == mkw_theme::THEME_LIGHT) return menu_text(UI_MENU_THEME_LIGHT);
    if (t == mkw_theme::THEME_GAME) {
        const mkw_theme::GameTheme *game = mkw_theme::game_theme(game_profile()->title_id);
        if (game) return game->name;
    }
    return menu_text(UI_MENU_THEME_DARK);
}

static void save_setting(const char *key, const char *value) {
    cfg_set(key, value);
    cfg_save();
    if (!cfg_last_save_ok()) rt_log("launcher: could not save setting %s", key);
}

static void cycle_theme(void) {
    static const char *values[] = {"dark", "light", "game"};
    int count = mkw_theme::game_theme(game_profile()->title_id) ? 3 : 2;
    int old = theme_kind();
    int next = (old + 1) % count;
    save_setting("NS2_MENU_THEME", values[next]);
    style_init();
    restyle(L.scale, true);
}

static void toggle_fullscreen(void) {
    bool full = (SDL_GetWindowFlags(L.window) & SDL_WINDOW_FULLSCREEN) != 0;
    bool next = !full;
    if (SDL_SetWindowFullscreen(L.window, next)) save_setting("NS2_FULLSCREEN", next ? "1" : "0");
    else rt_log("launcher: could not change full screen: %s", SDL_GetError());
}

static void profile_load(void) {
    if (L.profile_ready) return;
    const char *value = cfg_value("NS2_PLAYER_NAME");
    if (!value || !*value) value = "Player";
    size_t n = strlen(value);
    if (n > 32) {
        n = 32;
        while (n && ((unsigned char)value[n] & 0xC0) == 0x80) --n;
    }
    memcpy(L.name, value, n);
    L.name[n] = 0;
    L.profile_ready = true;
}

static bool back_pressed(void) {
    return ImGui::IsKeyPressed(ImGuiKey_Escape, false) || ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false);
}

static void profile_save(void) {
    char *begin = L.name;
    while (*begin && isspace((unsigned char)*begin)) ++begin;
    char *end = begin + strlen(begin);
    while (end > begin && isspace((unsigned char)end[-1])) --end;
    *end = 0;
    if (begin != L.name) memmove(L.name, begin, strlen(begin) + 1);
    if (!L.name[0]) {
        L.profile_note = menu_text(UI_LAUNCH_PROFILE_EMPTY);
        L.profile_note_color = L.colors.warn;
        return;
    }
    cfg_set("NS2_PLAYER_NAME", L.name);
    cfg_save();
    if (cfg_last_save_ok()) {
        L.profile_note = menu_text(UI_LAUNCH_PROFILE_SAVED);
        L.profile_note_color = L.colors.accent;
    } else {
        L.profile_note = menu_text(UI_LAUNCH_PROFILE_FAILED);
        L.profile_note_color = L.colors.warn;
    }
}

static void panel_begin(const char *id, const char *title, float w, float h) {
    float s = L.scale, panel_w = fminf(w - 48 * s, 960 * s), panel_h = fminf(h - 48 * s, 580 * s);
    float x = floorf((w - panel_w) * 0.5f), y = floorf((h - panel_h) * 0.5f);
    ImDrawList *draw = ImGui::GetBackgroundDrawList();
    draw->AddRectFilled(ImVec2(x + 4 * s, y + 12 * s), ImVec2(x + panel_w + 4 * s, y + panel_h + 12 * s),
                        rgba(18, 73, 113, 100), 22 * s);
    draw->AddRectFilled(ImVec2(x, y), ImVec2(x + panel_w, y + panel_h), L.colors.panel, 22 * s);
    draw->AddRect(ImVec2(x, y), ImVec2(x + panel_w, y + panel_h), with_alpha(L.colors.line, 0.85f),
                  22 * s, ImDrawFlags_RoundCornersAll, 1.5f * s);
    ImGui::SetNextWindowPos(ImVec2(x, y), ImGuiCond_Always);
    ImGui::SetNextWindowSize(ImVec2(panel_w, panel_h), ImGuiCond_Always);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(56 * s, 42 * s));
    ImGui::Begin(id, nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
                                 ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBackground);
    ImGui::PopStyleVar();
    ImGui::PushFont(L.font36);
    ImGui::TextUnformatted(title);
    ImGui::PopFont();
    ImGui::Dummy(ImVec2(0, 8 * s));
}

static void page_profile(float w, float h) {
    profile_load();
    panel_begin("##profile", menu_text(UI_LAUNCH_PROFILE_TITLE), w, h);
    float s = L.scale;
    ImGui::TextUnformatted(menu_text(UI_LAUNCH_PROFILE_NAME));
    ImGui::SetNextItemWidth(fminf(720 * s, ImGui::GetContentRegionAvail().x));
    ImGui::InputText("##player-name", L.name, sizeof L.name);
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + fminf(760 * s, ImGui::GetContentRegionAvail().x));
    ImGui::TextWrapped("%s", menu_text(UI_LAUNCH_PROFILE_DESC));
    ImGui::PopTextWrapPos();
    if (L.profile_note) ImGui::TextColored(v4(L.profile_note_color), "%s", L.profile_note);
    ImGui::Dummy(ImVec2(0, 18 * s));
    if (button("save", menu_text(UI_LAUNCH_SAVE), ImVec2(190 * s, 58 * s), true)) profile_save();
    ImGui::SameLine(0, 14 * s);
    bool back = button("back", menu_text(UI_LAUNCH_BACK), ImVec2(190 * s, 58 * s));
    if (!ImGui::GetIO().WantTextInput && back_pressed()) back = true;
    ImGui::End();
    if (back) {
        L.profile_note = nullptr;
        L.page = PAGE_MAIN;
    }
}

static void status_dot(ImDrawList *draw, float x, float y, bool ok, const char *text) {
    float r = 5 * L.scale;
    draw->AddCircleFilled(ImVec2(x + r, y + L.font26->FontSize * 0.55f), r, ok ? L.colors.accent : L.colors.warn, 16);
    draw->AddText(L.font26, L.font26->FontSize, ImVec2(x + 18 * L.scale, y), ok ? L.colors.dim : L.colors.warn, text);
}

static void update_card(float w, float h) {
    if (L.update.version.empty()) return;
    float s = L.scale, width = fminf(w * 0.43f, 590 * s), height = 293 * s, pad = 22 * s;
    ImVec2 a(w - width - 61 * s, h * 0.63f), b(a.x + width, a.y + height);
    ImGui::SetNextWindowPos(a, ImGuiCond_Always);
    ImGui::SetNextWindowSize(ImVec2(width, height), ImGuiCond_Always);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0, 0));
    ImGui::Begin("##release", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
                                       ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBackground |
                                       ImGuiWindowFlags_NoFocusOnAppearing);
    ImDrawList *draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(ImVec2(a.x + 3 * s, a.y + 6 * s), ImVec2(b.x + 3 * s, b.y + 6 * s),
                        rgba(0, 0, 0, 75), 16 * s);
    draw->AddRectFilled(a, b, L.colors.panel, 16 * s);
    draw->AddRect(a, b, with_alpha(L.colors.line, 0.9f), 16 * s);
    draw->AddRectFilled(ImVec2(a.x + pad, a.y + 15 * s), ImVec2(a.x + pad + 45 * s, a.y + 19 * s),
                        L.colors.accent, 2 * s);
    draw->AddText(L.font36, L.font36->FontSize, ImVec2(a.x + pad, a.y + 29 * s),
                  L.colors.text, menu_text(UI_LAUNCH_UPDATE_AVAILABLE));
    draw->AddText(L.font26, L.font26->FontSize, ImVec2(a.x + pad, a.y + 77 * s),
                  L.colors.dim, L.update.version.c_str());
    if (!L.update.summary.empty()) {
        ImVec4 bounds(a.x + pad, a.y + 114 * s, b.x - pad, a.y + 202 * s);
        draw->AddText(L.font26, L.font26->FontSize, ImVec2(bounds.x, bounds.y), L.colors.text,
                      L.update.summary.c_str(), nullptr, width - 2 * pad, &bounds);
    }
    ImGui::SetCursorScreenPos(ImVec2(a.x + pad, b.y - 70 * s));
    if (button("update", menu_text(UI_LAUNCH_UPDATE_NOW), ImVec2(fminf(236 * s, width - 2 * pad), 49 * s), true)
        && !L.shot_mode && !SDL_OpenURL(L.update.url.c_str())) {
        rt_log("launcher: could not open the GitHub release: %s", SDL_GetError());
    }
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", menu_text(UI_LAUNCH_UPDATE_HINT));
    ImGui::End();
    ImGui::PopStyleVar();
}

static void page_main(float w, float h) {
    float s = L.scale, left = 68 * s, width = fminf(560 * s, w * 0.47f), logo = 78 * s;
    float row = fmaxf(44 * s, 60 * s), play_h = 72 * s, gap = 8 * s;
    // ImGui adds ItemSpacing after each Dummy and row. Include the four settings-row gaps and the spacer before Quit;
    // the old estimate ended before the bottom of the final row, clipping its label at 720p.
    float total = logo + 12 * s + play_h + row * 5 + gap * 7 + 5 * s;
    float top = fmaxf(28 * s, (h - total) * 0.43f);
    if (mkw_theme::kMotif == mkw_theme::MOTIF_WONDER) {
        ImDrawList *bg = ImGui::GetBackgroundDrawList();
        ImVec2 a(left - 22 * s, top - 20 * s), b(left + width + 22 * s, top + total + 20 * s);
        bg->AddRectFilled(ImVec2(a.x + 4 * s, a.y + 10 * s), ImVec2(b.x + 4 * s, b.y + 10 * s),
                          rgba(19, 90, 128, 90), 24 * s);
        bg->AddRectFilled(a, b, L.colors.panel, 24 * s);
        bg->AddRect(a, b, with_alpha(L.colors.line, 0.75f), 24 * s, ImDrawFlags_RoundCornersAll, 1.25f * s);
    }
    ImGui::SetNextWindowPos(ImVec2(left, top), ImGuiCond_Always);
    ImGui::SetNextWindowSize(ImVec2(width, total), ImGuiCond_Always);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0, 0));
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(0, gap));
    ImGui::Begin("##main", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
                                        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBackground);
    ImDrawList *draw = ImGui::GetWindowDrawList();
    ImVec2 p = ImGui::GetCursorScreenPos();
    int first = draw->VtxBuffer.Size;
    if (L.icon) draw->AddImageRounded((ImTextureID)(intptr_t)L.icon, p, ImVec2(p.x + logo, p.y + logo),
                                      ImVec2(0, 0), ImVec2(1, 1), IM_COL32_WHITE, 12 * s, ImDrawFlags_RoundCornersAll);
    else add_bloom(draw, ImVec2(p.x + logo * 0.5f, p.y + logo * 0.5f), logo * 0.33f, 0, L.colors.accent);
    const char *title = game_profile()->display_name;
    float tx = p.x + logo + 18 * s, title_size = L.font36->FontSize;
    draw->AddText(L.font36, title_size, ImVec2(tx, p.y + (logo - title_size) * 0.36f), L.colors.text, title);
    const char *version = (rt_game_display_version && rt_game_display_version[0]) ? rt_game_display_version : "";
    char subtitle[256];
    snprintf(subtitle, sizeof subtitle, "%s: %s", menu_text(UI_LAUNCH_SUBTITLE), *version ? version : "unknown");
    draw->AddText(L.font26, L.font26->FontSize, ImVec2(tx, p.y + logo * 0.64f), L.colors.dim, subtitle);
    intro_apply(draw, first, L.shot_mode ? 1.0f : ease_out((float)((ImGui::GetTime() - L.intro_at) / 0.45)), s);
    ImGui::Dummy(ImVec2(width, logo + 12 * s));
    first = draw->VtxBuffer.Size;
    bool play = button("play", menu_text(UI_LAUNCH_PLAY), ImVec2(width, play_h), true, true);
    intro_apply(draw, first, L.shot_mode ? 1.0f : ease_out((float)((ImGui::GetTime() - L.intro_at - 0.08) / 0.42)), s);

    char value[256];
    const char *name = cfg_value("NS2_PLAYER_NAME");
    if (!name || !*name) name = "Player";
    snprintf(value, sizeof value, menu_text(UI_LAUNCH_PLAYER), name);
    if (menu_item("profile", value, nullptr, width)) {
        L.page = PAGE_PROFILE;
        L.profile_note = nullptr;
        L.profile_ready = false;
    }
    const char *theme = theme_name();
    snprintf(value, sizeof value, menu_text(UI_LAUNCH_THEME), theme);
    if (menu_item("theme", value, nullptr, width)) cycle_theme();
    const char *display = cfg_bool("NS2_FULLSCREEN") ? menu_text(UI_LAUNCH_FULLSCREEN) : menu_text(UI_LAUNCH_WINDOWED);
    snprintf(value, sizeof value, menu_text(UI_LAUNCH_WINDOW), display);
    if (menu_item("display", value, nullptr, width)) toggle_fullscreen();
    const char *show = cfg_bool("NS2_SHOW_LAUNCHER") ? menu_text(UI_MENU_ON) : menu_text(UI_MENU_OFF);
    snprintf(value, sizeof value, menu_text(UI_LAUNCH_SHOW), show);
    if (menu_item("show", value, nullptr, width)) {
        bool next = !cfg_bool("NS2_SHOW_LAUNCHER");
        save_setting("NS2_SHOW_LAUNCHER", next ? "1" : "0");
    }
    ImGui::Dummy(ImVec2(0, 5 * s));
    if (menu_item("quit", menu_text(UI_LAUNCH_QUIT), nullptr, width)) L.result = LAUNCHER_QUIT;
    if (play || (L.shot_mode == false && getenv("NS2_LAUNCHER_PLAY") && !strcmp(getenv("NS2_LAUNCHER_PLAY"), "1")))
        L.result = LAUNCHER_PLAY;
    ImGui::End();
    ImGui::PopStyleVar(2);
    update_card(w, h);

    bool files = path_exists(L.exefs) && path_exists(L.romfs);
    bool shaders = L.shaders_ready;
    float bottom_y = h - 36 * s;
    status_dot(ImGui::GetForegroundDrawList(), left, bottom_y - 26 * s, files, menu_text(files ? UI_LAUNCH_FILES_READY : UI_LAUNCH_FILES_MISSING));
    status_dot(ImGui::GetForegroundDrawList(), left, bottom_y, shaders, menu_text(shaders ? UI_LAUNCH_SHADERS_READY : UI_LAUNCH_SHADERS_MISSING));
    ImDrawList *fg = ImGui::GetForegroundDrawList();
    const char *privacy = menu_text(UI_LAUNCH_NO_GAME_DATA);
    const char *port = rt_port_version;
    char release[256];
    snprintf(release, sizeof release, menu_text(UI_LAUNCH_PORT_VERSION), port);
    ImVec2 privacy_size = L.font26->CalcTextSizeA(L.font26->FontSize, FLT_MAX, 0, privacy);
    ImVec2 release_size = L.font26->CalcTextSizeA(L.font26->FontSize, FLT_MAX, 0, release);
    float right = w - 28 * s;
    fg->AddText(L.font26, L.font26->FontSize, ImVec2(right - privacy_size.x, bottom_y - 26 * s), L.colors.dim, privacy);
    fg->AddText(L.font26, L.font26->FontSize, ImVec2(right - release_size.x, bottom_y), L.colors.dim, release);

    if (L.shot_mode && L.shot_at == 1 && L.result < 0) L.result = LAUNCHER_QUIT;
}

static bool save_shot(void) {
    const char *path = getenv("NS2_LAUNCHER_SHOT_OUT");
    if (!path || !*path) path = "launcher.png";
    SDL_Surface *pixels = SDL_RenderReadPixels(L.renderer, nullptr);
    bool ok = pixels && SDL_SavePNG(pixels, path);
    if (pixels) SDL_DestroySurface(pixels);
    if (!ok) rt_log("launcher: could not save screenshot %s: %s", path, SDL_GetError());
    else rt_log("launcher: screenshot saved to %s", path);
    return ok;
}

static void cleanup(void) {
    if (ImGui::GetCurrentContext()) {
        if (L.fonts_ready) ImGui_ImplSDLRenderer3_DestroyFontsTexture();
        if (L.renderer_backend_ready) ImGui_ImplSDLRenderer3_Shutdown();
        if (L.sdl_backend_ready) ImGui_ImplSDL3_Shutdown();
        ImGui::DestroyContext();
    }
    free_images();
    if (L.renderer) SDL_DestroyRenderer(L.renderer);
    if (L.window) SDL_DestroyWindow(L.window);
    L.renderer = nullptr;
    L.window = nullptr;
    SDL_Quit();
}

} // namespace

extern "C" int launcher_run(const char *exefs, const char *romfs) {
    L = {};
    L.result = -1;
    L.page = PAGE_MAIN;
    L.exefs = exefs;
    L.romfs = romfs;
    L.shot_mode = false;
    if (const char *shot = getenv("NS2_LAUNCHER_SHOT")) {
        char *end = nullptr;
        long frame = strtol(shot, &end, 10);
        if (end != shot && frame > 0) L.shot_at = frame, L.shot_mode = true;
    }
    if (const char *motion = getenv("NS2_LAUNCHER_SHOT_MOTION"))
        L.shot_motion = motion[0] && strcmp(motion, "0");
    if (const char *page = getenv("NS2_LAUNCHER_PAGE"))
        if (!strcmp(page, "profile")) L.page = PAGE_PROFILE;
    exe_dir(L.exe_dir, sizeof L.exe_dir);
    L.shaders_ready = shader_warm_ready(L.exe_dir);
    if (!open_window()) return LAUNCHER_PLAY;
    if (!L.shot_mode) {
        launcher_release::start(L.exe_dir, rt_port_version);
    } else if (const char *test_update = getenv("NS2_LAUNCHER_SHOT_UPDATE"); test_update && !strcmp(test_update, "1")) {
        launcher_release::from_feed("example/setup", rt_port_version,
            R"([{ "tag_name": "v9.99.0", "draft": false, "body": "Improved controller navigation.\nFaster startup on older PCs." }])",
            L.update);
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO &io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.LogFilename = nullptr;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    style_init();
    if (!ImGui_ImplSDL3_InitForSDLRenderer(L.window, L.renderer)) {
        rt_log("launcher: could not initialize Dear ImGui's SDL3 platform back end");
        cleanup();
        return LAUNCHER_PLAY;
    }
    L.sdl_backend_ready = true;
    if (!ImGui_ImplSDLRenderer3_Init(L.renderer)) {
        rt_log("launcher: could not initialize Dear ImGui's SDL3 renderer back end");
        cleanup();
        return LAUNCHER_PLAY;
    }
    L.renderer_backend_ready = true;
    load_images();
    float initial_scale = 720.0f / 1080.0f;
    restyle(initial_scale, true);
    if (L.shot_mode && !L.shot_motion) L.intro_at = -1.0;

    const bool play_test = getenv("NS2_LAUNCHER_PLAY") && !strcmp(getenv("NS2_LAUNCHER_PLAY"), "1");
    for (long frame = 1; L.result < 0; ++frame) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_QUIT || event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) L.result = LAUNCHER_QUIT;
            if (event.type == SDL_EVENT_KEY_DOWN && event.key.scancode == SDL_SCANCODE_F11 && !event.key.repeat)
                toggle_fullscreen();
            if (L.shot_mode) continue;
            SDL_ConvertEventToRenderCoordinates(L.renderer, &event);
            ImGui_ImplSDL3_ProcessEvent(&event);
        }
        int w = 0, h = 0;
        SDL_GetRenderOutputSize(L.renderer, &w, &h);
        if (w <= 0 || h <= 0) continue;
        restyle((float)h / 1080.0f);
        ImGui_ImplSDLRenderer3_NewFrame();
        ImGui_ImplSDL3_NewFrame();
        io.DisplaySize = ImVec2((float)w, (float)h);
        io.DisplayFramebufferScale = ImVec2(1, 1);
        ImGui::NewFrame();
        if (L.intro_at == 0) L.intro_at = ImGui::GetTime();
        if ((!L.shot_mode || L.shot_motion) && (SDL_GetWindowFlags(L.window) & SDL_WINDOW_INPUT_FOCUS))
            L.motion_time += io.DeltaTime;
        ImDrawList *bg = ImGui::GetBackgroundDrawList();
        if (!L.shot_mode && L.update.version.empty()) launcher_release::available(L.update);
        backdrop_draw(bg, (float)w, (float)h);
        if (L.page == PAGE_MAIN) draw_card(bg, (float)w, (float)h);
        if (L.page == PAGE_MAIN) page_main((float)w, (float)h);
        else page_profile((float)w, (float)h);
        ImGui::Render();
        SDL_SetRenderDrawColor(L.renderer, 0, 0, 0, 255);
        SDL_RenderClear(L.renderer);
        ImGui_ImplSDLRenderer3_RenderDrawData(ImGui::GetDrawData(), L.renderer);
        if (!L.shown) {
            SDL_ShowWindow(L.window);
            L.shown = true;
        }
        if (L.shot_mode && frame == L.shot_at) {
            save_shot();
            L.result = LAUNCHER_QUIT;
        }
        if (play_test && frame == 1) L.result = LAUNCHER_PLAY;
        SDL_RenderPresent(L.renderer);
    }
    int result = L.result < 0 ? LAUNCHER_QUIT : L.result;
    cleanup();
    return result;
}
