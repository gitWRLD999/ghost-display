package com.vertex.ghost;

import android.net.*;
import android.os.SystemClock;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

/** app_process CLI; stdout is JSON, except a successful screenshot without --out. */
public final class GhostCtl {
  private static String take(List<String> args, String key, String fallback) {
    int i = args.indexOf(key);
    if (i < 0) return fallback;
    if (i + 1 >= args.size()) throw new IllegalArgumentException("missing " + key + " value");
    args.remove(i);
    return args.remove(i);
  }

  private static void bootstrap(String action) throws Exception {
    String result =
        GhostDisplayUserService.run(
            "/system/bin/am",
            "broadcast",
            "--user",
            "0",
            "-n",
            "com.vertex.ghost/.GhostCommandReceiver",
            "-a",
            "com.vertex.ghost." + action,
            "--receiver-foreground");
    if (result.contains("SecurityException")) throw new IOException(result);
  }

  public static void main(String[] argv) {
    int rc = 0;
    try {
      rc = execute(argv);
    } catch (Throwable e) {
      System.out.println(GhostDisplayUserService.json("ok", false, "error", e.toString()));
      rc = 1;
    }
    System.exit(rc);
  }

  private static int execute(String[] argv) throws Exception {
    if (argv.length == 0 || argv[0].equals("help") || argv[0].equals("--help")) {
      System.out.println(
          "ghostctl start|stop|status|screenshot|open-app PKG|open-component CMP|open-url URL|tap X"
              + " Y|long-press X Y [MS]|swipe X1 Y1 X2 Y2 [MS]|scroll X1 Y1 X2 Y2 [MS]|text"
              + " TEXT|key CODE|back|home|rotate|dump|viewer\n"
              + "Screenshot options: --out DEVICE_PATH --format png|jpeg --quality 80 --max-width"
              + " 800\n"
              + "All commands return JSON; screenshot without --out returns binary. Requires shell"
              + " via adb or rish.");
      return 0;
    }
    ArrayList<String> a = new ArrayList<>(Arrays.asList(argv));
    String cmd = a.remove(0);
    a.remove("--json");
    if (cmd.equals("viewer")) {
      String output =
          GhostDisplayUserService.run(
              "/system/bin/am",
              "start",
              "--user",
              "0",
              "--display",
              "0",
              "-n",
              "com.vertex.ghost/.GhostViewerActivity");
      System.out.println(
          GhostDisplayUserService.json("ok", !output.contains("Error:"), "output", output));
      return output.contains("Error:") ? 1 : 0;
    }
    JSONObject q = GhostDisplayUserService.json("command", cmd);
    String out = null;
    if (cmd.equals("screenshot")) {
      out = take(a, "--out", null);
      q.put("format", take(a, "--format", "png"));
      q.put("quality", Integer.parseInt(take(a, "--quality", "80")));
      q.put("maxWidth", Integer.parseInt(take(a, "--max-width", "0")));
    } else if (cmd.equals("start")) {
      q.put("width", Integer.parseInt(take(a, "--width", "1200")));
      q.put("height", Integer.parseInt(take(a, "--height", "1920")));
      q.put("density", Integer.parseInt(take(a, "--density", "320")));
    } else if (cmd.equals("open-app")
        || cmd.equals("open-component")
        || cmd.equals("open-url")
        || cmd.equals("text")
        || cmd.equals("key")) {
      if (a.size() != 1) throw new IllegalArgumentException("expected_one_argument_quote_text");
      q.put(
          cmd.equals("open-app")
              ? "package"
              : cmd.equals("open-component")
                  ? "component"
                  : cmd.equals("open-url") ? "url" : cmd.equals("key") ? "keycode" : "text",
          a.remove(0));
    } else if (cmd.equals("tap") || cmd.equals("long-press")) {
      q.put("x", Integer.parseInt(a.remove(0)));
      q.put("y", Integer.parseInt(a.remove(0)));
      if (!a.isEmpty()) q.put("duration", Integer.parseInt(a.remove(0)));
    } else if (cmd.equals("swipe") || cmd.equals("scroll")) {
      for (String k : new String[] {"x1", "y1", "x2", "y2"})
        q.put(k, Integer.parseInt(a.remove(0)));
      if (!a.isEmpty()) q.put("duration", Integer.parseInt(a.remove(0)));
    }
    if (!a.isEmpty()) throw new IllegalArgumentException("unexpected_arguments " + a);
    if (cmd.equals("start")) bootstrap("HEADLESS_START");
    if (cmd.equals("stop")) bootstrap("HEADLESS_STOP");
    LocalSocket s = null;
    for (int n = 0; n < (cmd.equals("start") ? 30 : 1); n++) {
      try {
        s = new LocalSocket();
        s.connect(
            new LocalSocketAddress(
                GhostDisplayUserService.SOCKET, LocalSocketAddress.Namespace.ABSTRACT));
        break;
      } catch (IOException e) {
        if (s != null) s.close();
        s = null;
        if (cmd.equals("start")) SystemClock.sleep(500);
      }
    }
    if (s == null) {
      boolean ok = cmd.equals("status") || cmd.equals("stop");
      System.out.println(
          GhostDisplayUserService.json(
              "ok",
              ok,
              "running",
              false,
              "displayId",
              -1,
              "width",
              JSONObject.NULL,
              "height",
              JSONObject.NULL,
              "density",
              JSONObject.NULL,
              "rotation",
              JSONObject.NULL,
              "state",
              "OFF",
              "currentPackage",
              JSONObject.NULL,
              "currentActivity",
              JSONObject.NULL,
              "captureHealth",
              "backend_unavailable",
              "inputHealth",
              "backend_unavailable"));
      return ok ? 0 : 1;
    }
    try (LocalSocket socket = s) {
      socket.setSoTimeout(20000);
      socket.getOutputStream().write((q + "\n").getBytes(StandardCharsets.UTF_8));
      InputStream in = socket.getInputStream();
      JSONObject result = new JSONObject(GhostDisplayUserService.readLine(in));
      if (!cmd.equals("screenshot") || !result.optBoolean("ok")) {
        System.out.println(result);
        return result.optBoolean("ok") ? 0 : 1;
      }
      long left = result.getLong("byteLength");
      if (left < 0 || left > 50000000) throw new IOException("invalid_image_length");
      OutputStream dest = out == null ? System.out : new FileOutputStream(out);
      try {
        byte[] buf = new byte[65536];
        while (left > 0) {
          int n = in.read(buf, 0, (int) Math.min(left, buf.length));
          if (n < 0) throw new EOFException("truncated_frame");
          dest.write(buf, 0, n);
          left -= n;
        }
        dest.flush();
      } finally {
        if (out != null) dest.close();
      }
      if (out != null) {
        result.put("path", out);
        System.out.println(result);
      }
      return 0;
    }
  }
}
