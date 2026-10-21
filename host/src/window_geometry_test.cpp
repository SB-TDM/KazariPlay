#include "window.hpp"

#include <iostream>

namespace {

int failures = 0;

void expect(LRESULT actual, LRESULT expected, const char* message) {
    if (actual != expected) {
        std::cerr << "FAIL: " << message << " expected=" << expected
                  << " actual=" << actual << '\n';
        ++failures;
    }
}

}  // namespace

int main() {
    const RECT client{0, 0, 1200, 800};
    const CaptionRects caps = captionRectsFor(client, 96);
    const auto center = [](const RECT& rect) {
        return POINT{(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2};
    };
    expect(regionAt(POINT{10, 20}, caps, client, 96, false), HTCAPTION,
           "titlebar blank");
    expect(regionAt(center(caps.maximize), caps, client, 96, false), HTMAXBUTTON,
           "maximize button");
    expect(regionAt(center(caps.close), caps, client, 96, false), HTCLOSE,
           "close button");
    expect(regionAt(POINT{3, 300}, caps, client, 96, false), HTLEFT,
           "left resize edge");
    expect(regionAt(POINT{600, 300}, caps, client, 96, false), HTCLIENT,
           "client body");

    const CaptionRects scaled = captionRectsFor(client, 144);
    expect(regionAt(POINT{20, 30}, scaled, client, 144, false), HTCAPTION,
           "150 percent titlebar");
    expect(regionAt(center(scaled.maximize), scaled, client, 144, false), HTMAXBUTTON,
           "150 percent maximize button");
    expect(regionAt(POINT{3, 300}, scaled, client, 144, false), HTLEFT,
           "150 percent edge");

    if (failures != 0) {
        std::cerr << failures << " geometry check(s) failed\n";
        return 1;
    }
    std::cout << "HOST_WINDOW_GEOMETRY_TEST PASS\n";
    return 0;
}
