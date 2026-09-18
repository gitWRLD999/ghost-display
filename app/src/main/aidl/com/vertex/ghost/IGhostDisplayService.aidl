package com.vertex.ghost;
import android.os.ParcelFileDescriptor;

// Binder interface for the Shizuku UserService that owns the headless display.
// Runs as shell UID 2000, so it can use trusted virtual-display flags.
interface IGhostDisplayService {
    String startDisplay(int width, int height, int density) = 0;
    String stopDisplay() = 1;
    String getStatus() = 2;
    int getDisplayId() = 3;
    String screenshot(String path) = 4;
    String openApp(String pkg) = 5;
    String openComponent(String component) = 6;
    String openUrl(String url) = 7;
    String tap(int x, int y) = 8;
    String swipe(int x1, int y1, int x2, int y2, int durationMs) = 9;
    String setPanelPower(boolean on) = 10;
    String setStayAwake(boolean on) = 11;
    String command(String requestJson) = 12;
    ParcelFileDescriptor capture(String format, int quality, int maxWidth) = 13;
    // Shizuku's reserved destroy transaction.
    void destroy() = 16777114;
}
