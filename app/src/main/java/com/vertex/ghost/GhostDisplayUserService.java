package com.vertex.ghost;

import android.content.*;
import android.graphics.*;
import android.hardware.display.*;
import android.media.*;
import android.net.*;
import android.os.*;
import android.view.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.regex.*;
import org.json.*;

/** Shell-owned display. The ordinary app never creates privileged framework objects. */
public class GhostDisplayUserService extends IGhostDisplayService.Stub {
  static final String SOCKET = "com.vertex.ghost.control.v1";
  private final Context shell;
  private final GhostVirtualDevice virtualDevice;
  private final int appUid;
  private final LocalServerSocket server;
  private final ExecutorService clients =
      new ThreadPoolExecutor(2, 4, 30, TimeUnit.SECONDS, new ArrayBlockingQueue<>(16));
  private final Object frameLock = new Object();
  private final JSONObject resolvedFlags = new JSONObject();
  private VirtualDisplay vd;
  private ImageReader reader;
  private HandlerThread frames;
  private Bitmap frame;
  private int frameWidth, frameHeight;
  private PowerManager.WakeLock displayWake, cpuWake;
  private volatile int id = -1, width, height, density, flags;
  private volatile long frameSequence, lastFrameMs;
  private volatile String captureError = "no_frame", inputHealth = "untested";
  private volatile boolean closed;

  public GhostDisplayUserService(Context context) throws Exception {
    if (android.os.Process.myUid() != 2000 && android.os.Process.myUid() != 0)
      throw new SecurityException("Ghost backend requires Shizuku shell identity");
    appUid = context.getPackageManager().getApplicationInfo("com.vertex.ghost", 0).uid;
    Context packageContext =
        context.createPackageContext("com.android.shell", Context.CONTEXT_IGNORE_SECURITY);
    shell =
        new ContextWrapper(packageContext) {
          @Override
          public Context getApplicationContext() {
            return this;
          }

          @Override
          public String getOpPackageName() {
            return "com.android.shell";
          }

          @Override
          public android.content.AttributionSource getAttributionSource() {
            return new android.content.AttributionSource.Builder(android.os.Process.myUid())
                .setPackageName("com.android.shell")
                .build();
          }
        };
    virtualDevice = new GhostVirtualDevice(shell);
    // Atomic abstract socket bind also serves as the process singleton lock.
    server = new LocalServerSocket(SOCKET);
    new Thread(this::acceptLoop, "ghost-control").start();
  }

  private void authorize() {
    int uid = Binder.getCallingUid();
    if (uid != 0 && uid != 2000 && uid != appUid) throw new SecurityException("unauthorized_uid");
  }

  static JSONObject json(Object... kv) {
    JSONObject o = new JSONObject();
    try {
      for (int i = 0; i < kv.length; i += 2) o.put((String) kv[i], kv[i + 1]);
    } catch (JSONException e) {
      throw new IllegalArgumentException(e);
    }
    return o;
  }

  private static String message(Throwable t) {
    while (t.getCause() != null) t = t.getCause();
    return t.getClass().getSimpleName() + ": " + t.getMessage();
  }

  private int resolveFlags() throws Exception {
    int value = 0;
    for (String name :
        new String[] {
          "OWN_CONTENT_ONLY",
          "SUPPORTS_TOUCH",
          "DESTROY_CONTENT_ON_REMOVAL",
          "TRUSTED",
          "DEVICE_DISPLAY_GROUP",
          "ALWAYS_UNLOCKED",
          "TOUCH_FEEDBACK_DISABLED",
          "OWN_FOCUS",
          "STEAL_TOP_FOCUS_DISABLED"
        }) {
      Field f = DisplayManager.class.getDeclaredField("VIRTUAL_DISPLAY_FLAG_" + name);
      f.setAccessible(true);
      int n = f.getInt(null);
      value |= n;
      resolvedFlags.put(name, n);
    }
    return value;
  }

  private ImageReader createReader(int w, int h) {
    ImageReader ir = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3);
    ir.setOnImageAvailableListener(
        r -> {
          try (Image img = r.acquireLatestImage()) {
            if (img == null) return;
            Image.Plane p = img.getPlanes()[0];
            synchronized (frameLock) {
              if (r != reader) return;
              int paddedWidth = p.getRowStride() / p.getPixelStride();
              if (frame == null
                  || frame.getWidth() != paddedWidth
                  || frame.getHeight() != img.getHeight()) {
                if (frame != null) frame.recycle();
                frame = Bitmap.createBitmap(paddedWidth, img.getHeight(), Bitmap.Config.ARGB_8888);
              }
              frame.copyPixelsFromBuffer(p.getBuffer());
              frameWidth = img.getWidth();
              frameHeight = img.getHeight();
              frameSequence++;
              lastFrameMs = SystemClock.elapsedRealtime();
              captureError = "";
              frameLock.notifyAll();
            }
          } catch (Throwable t) {
            captureError = message(t);
          }
        },
        new Handler(frames.getLooper()));
    return ir;
  }

  private void requireDisplay() {
    if (vd == null || id < 1 || !vd.getDisplay().isValid())
      throw new IllegalStateException("display_not_running");
  }

  private JSONObject start(int w, int h, int dpi) throws Exception {
    if (vd != null && vd.getDisplay().isValid()) return status(false);
    if (w < 320 || h < 320 || w > 2560 || h > 2560 || dpi < 120 || dpi > 640)
      throw new IllegalArgumentException("dimensions_out_of_range");
    cleanup();
    try {
      flags = resolveFlags();
      width = w;
      height = h;
      density = dpi;
      frames = new HandlerThread("ghost-frames");
      frames.start();
      reader = createReader(w, h);
      vd =
          virtualDevice.create(
              new VirtualDisplayConfig.Builder("Ghost Headless", w, h, dpi)
                  .setSurface(reader.getSurface())
                  .setFlags(flags)
                  .build(),
              command -> new Handler(frames.getLooper()).post(command));
      if (vd == null) throw new IllegalStateException("createVirtualDisplay returned null");
      id = vd.getDisplay().getDisplayId();
      if (id < 1) throw new IllegalStateException("refusing_physical_display");
      if (displayGroupId() <= 0)
        throw new IllegalStateException("independent_display_group_required");
      PowerManager pm = shell.getSystemService(PowerManager.class);
      Method newLock =
          PowerManager.class.getDeclaredMethod("newWakeLock", int.class, String.class, int.class);
      newLock.setAccessible(true);
      displayWake =
          (PowerManager.WakeLock)
              newLock.invoke(pm, PowerManager.SCREEN_BRIGHT_WAKE_LOCK, "ghost:display", id);
      displayWake.setReferenceCounted(false);
      displayWake.acquire();
      cpuWake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ghost:cpu");
      cpuWake.setReferenceCounted(false);
      cpuWake.acquire();
      launch("open-component", "com.vertex.ghost/.GhostBlankActivity");
      return status(false);
    } catch (Exception e) {
      cleanup();
      throw e;
    }
  }

  private void cleanup() {
    id = -1;
    if (displayWake != null) {
      if (displayWake.isHeld()) displayWake.release();
      displayWake = null;
    }
    if (cpuWake != null) {
      if (cpuWake.isHeld()) cpuWake.release();
      cpuWake = null;
    }
    if (vd != null) {
      vd.release();
      vd = null;
    }
    try {
      virtualDevice.closeDevice();
    } catch (Exception e) {
      android.util.Log.e("GhostDisplay", "VirtualDevice cleanup failed", e);
    }
    synchronized (frameLock) {
      if (reader != null) {
        reader.close();
        reader = null;
      }
      if (frame != null) {
        frame.recycle();
        frame = null;
      }
      frameSequence = 0;
      lastFrameMs = 0;
      captureError = "no_frame";
    }
    if (frames != null) {
      frames.quitSafely();
      frames = null;
    }
    inputHealth = "untested";
  }

  private JSONObject status(boolean foreground) throws Exception {
    boolean running = vd != null && vd.getDisplay().isValid();
    JSONObject o =
        json(
            "ok",
            true,
            "running",
            running,
            "displayId",
            running ? id : -1,
            "width",
            width,
            "height",
            height,
            "density",
            density,
            "rotation",
            running ? vd.getDisplay().getRotation() : 0,
            "orientation",
            width > height ? "landscape" : "portrait",
            "state",
            running ? stateName(vd.getDisplay().getState()) : "OFF",
            "backendUid",
            android.os.Process.myUid(),
            "backendPid",
            android.os.Process.myPid(),
            "ownerPackage",
            shell.getPackageName(),
            "flags",
            flags,
            "virtualDeviceId",
            virtualDevice.deviceId(),
            "associationId",
            virtualDevice.associationId(),
            "resolvedFlags",
            resolvedFlags,
            "captureHealth",
            captureError.isEmpty() ? "ready" : captureError,
            "inputHealth",
            inputHealth,
            "frameSequence",
            frameSequence,
            "frameAgeMs",
            lastFrameMs == 0 ? -1 : SystemClock.elapsedRealtime() - lastFrameMs,
            "displayWakeLock",
            displayWake != null && displayWake.isHeld(),
            "currentPackage",
            JSONObject.NULL,
            "currentActivity",
            JSONObject.NULL);
    if (running)
      try {
        Class<?> infoClass = Class.forName("android.view.DisplayInfo");
        Object info = infoClass.getConstructor().newInstance();
        Display.class.getMethod("getDisplayInfo", infoClass).invoke(vd.getDisplay(), info);
        o.put("displayGroupId", infoClass.getField("displayGroupId").getInt(info));
      } catch (ReflectiveOperationException e) {
        o.put("displayGroupId", JSONObject.NULL);
      }
    if (foreground && running) {
      Matcher m =
          Pattern.compile("mCurrentFocus=Window\\{[^}]* u\\d+ ([^ }]+)")
              .matcher(displaySection(run("/system/bin/dumpsys", "window", "displays")));
      if (m.find()) {
        String c = m.group(1);
        o.put("currentActivity", c);
        o.put("currentPackage", c.split("/")[0]);
      }
    }
    return o;
  }

  private String stateName(int state) {
    return state == Display.STATE_ON
        ? "ON"
        : state == Display.STATE_OFF ? "OFF" : String.valueOf(state);
  }

  private int displayGroupId() throws Exception {
    Class<?> infoClass = Class.forName("android.view.DisplayInfo");
    Object info = infoClass.getConstructor().newInstance();
    Display.class.getMethod("getDisplayInfo", infoClass).invoke(vd.getDisplay(), info);
    return infoClass.getField("displayGroupId").getInt(info);
  }

  private String displaySection(String text) {
    String marker = "Display: mDisplayId=" + id;
    int start = text.indexOf(marker);
    if (start < 0) return "";
    int end = text.indexOf("Display: mDisplayId=", start + marker.length());
    return text.substring(start, end < 0 ? text.length() : end);
  }

  private void point(int x, int y) {
    if (x < 0 || y < 0 || x >= width || y >= height)
      throw new IllegalArgumentException("coordinate_out_of_bounds");
  }

  private void inject(InputEvent event) throws Exception {
    InputEvent.class.getMethod("setDisplayId", int.class).invoke(event, id);
    Class<?> c = Class.forName("android.hardware.input.InputManagerGlobal");
    Object im = c.getMethod("getInstance").invoke(null);
    boolean ok =
        (Boolean) c.getMethod("injectInputEvent", InputEvent.class, int.class).invoke(im, event, 2);
    if (!ok) throw new IllegalStateException("input_injection_rejected");
  }

  private void touch(int x1, int y1, int x2, int y2, int duration) throws Exception {
    point(x1, y1);
    point(x2, y2);
    duration = Math.max(0, Math.min(5000, duration));
    long down = SystemClock.uptimeMillis();
    motion(down, down, MotionEvent.ACTION_DOWN, x1, y1);
    try {
      for (int t = 16; t < duration; t += 16) {
        SystemClock.sleep(16);
        float f = (float) t / duration;
        motion(
            down,
            SystemClock.uptimeMillis(),
            MotionEvent.ACTION_MOVE,
            x1 + (x2 - x1) * f,
            y1 + (y2 - y1) * f);
      }
    } finally {
      motion(down, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, x2, y2);
    }
  }

  private void motion(long down, long now, int action, float x, float y) throws Exception {
    MotionEvent e =
        MotionEvent.obtain(
            down, now, action, x, y, action == MotionEvent.ACTION_UP ? 0 : 1, 1, 0, 1, 1, 0, 0);
    e.setSource(InputDevice.SOURCE_TOUCHSCREEN);
    try {
      inject(e);
    } finally {
      e.recycle();
    }
  }

  private void key(int code) throws Exception {
    if (code == KeyEvent.KEYCODE_POWER
        || code == KeyEvent.KEYCODE_SLEEP
        || code == KeyEvent.KEYCODE_WAKEUP
        || code == KeyEvent.KEYCODE_HOME)
      throw new IllegalArgumentException("global_key_disallowed_use_home_command");
    long now = SystemClock.uptimeMillis();
    inject(
        new KeyEvent(
            now,
            now,
            KeyEvent.ACTION_DOWN,
            code,
            0,
            0,
            KeyCharacterMap.VIRTUAL_KEYBOARD,
            0,
            0,
            InputDevice.SOURCE_KEYBOARD));
    inject(
        new KeyEvent(
            now,
            now,
            KeyEvent.ACTION_UP,
            code,
            0,
            0,
            KeyCharacterMap.VIRTUAL_KEYBOARD,
            0,
            0,
            InputDevice.SOURCE_KEYBOARD));
  }

  private String launch(String kind, String value) throws Exception {
    ArrayList<String> args =
        new ArrayList<>(
            Arrays.asList(
                "/system/bin/am",
                "start",
                "--user",
                "0",
                "--display",
                String.valueOf(id),
                "-f",
                "0x18000000"));
    if (kind.equals("open-app")) {
      Intent intent = shell.getPackageManager().getLaunchIntentForPackage(value);
      if (intent == null || intent.getComponent() == null)
        throw new IllegalArgumentException("no_launcher_activity");
      args.add("-n");
      args.add(intent.getComponent().flattenToString());
    } else if (kind.equals("open-component")) {
      args.add("-n");
      args.add(value);
    } else {
      args.add("-a");
      args.add(Intent.ACTION_VIEW);
      args.add("-d");
      args.add(value);
    }
    String output = run(args.toArray(new String[0]));
    if (output.contains("Error:") || output.contains("Exception"))
      throw new IllegalStateException(output);
    return output;
  }

  @Override
  public synchronized String command(String requestJson) {
    authorize();
    long identity = Binder.clearCallingIdentity();
    try {
      JSONObject q = new JSONObject(requestJson);
      String cmd = q.getString("command");
      if (cmd.equals("start"))
        return start(q.optInt("width", 1200), q.optInt("height", 1920), q.optInt("density", 320))
            .toString();
      if (cmd.equals("stop")) {
        cleanup();
        virtualDevice.removeAssociation();
        return status(false).toString();
      }
      if (cmd.equals("status")) return status(true).toString();
      requireDisplay();
      JSONObject result = json("ok", true, "displayId", id);
      switch (cmd) {
        case "open-app":
          result.put("output", launch(cmd, q.getString("package")));
          break;
        case "open-component":
          result.put("output", launch(cmd, q.getString("component")));
          break;
        case "open-url":
          result.put("output", launch(cmd, q.getString("url")));
          break;
        case "home":
          result.put("output", launch("open-component", "com.vertex.ghost/.GhostBlankActivity"));
          break;
        case "tap":
          touch(q.getInt("x"), q.getInt("y"), q.getInt("x"), q.getInt("y"), 0);
          inputHealth = "ok";
          break;
        case "long-press":
          touch(
              q.getInt("x"),
              q.getInt("y"),
              q.getInt("x"),
              q.getInt("y"),
              q.optInt("duration", 700));
          inputHealth = "ok";
          break;
        case "swipe":
        case "scroll":
          touch(
              q.getInt("x1"),
              q.getInt("y1"),
              q.getInt("x2"),
              q.getInt("y2"),
              q.optInt("duration", 350));
          inputHealth = "ok";
          break;
        case "text":
          {
            String s = q.getString("text");
            if (s.length() > 10000) throw new IllegalArgumentException("text_too_long");
            KeyEvent[] events =
                KeyCharacterMap.load(KeyCharacterMap.VIRTUAL_KEYBOARD).getEvents(s.toCharArray());
            if (events == null)
              throw new IllegalArgumentException("text_not_supported_by_virtual_keyboard");
            for (KeyEvent e : events) inject(e);
            inputHealth = "ok";
            break;
          }
        case "back":
          key(KeyEvent.KEYCODE_BACK);
          inputHealth = "ok";
          break;
        case "key":
          {
            String name = q.getString("keycode");
            int code;
            try {
              code = Integer.parseInt(name);
            } catch (NumberFormatException e) {
              code =
                  KeyEvent.keyCodeFromString(
                      name.startsWith("KEYCODE_") ? name : "KEYCODE_" + name);
            }
            if (code <= 0) throw new IllegalArgumentException("unknown_key");
            key(code);
            inputHealth = "ok";
            break;
          }
        case "dump":
          result.put(
              "windowDump", displaySection(run("/system/bin/dumpsys", "window", "displays")));
          break;
        case "rotate":
          {
            int w = height, h = width;
            ImageReader old = reader;
            synchronized (frameLock) {
              reader = createReader(w, h);
              if (frame != null) {
                frame.recycle();
                frame = null;
              }
            }
            vd.resize(w, h, density);
            vd.setSurface(reader.getSurface());
            old.close();
            width = w;
            height = h;
            result = status(false);
            break;
          }
        case "focus":
          result.put("note", "focus_is_display_scoped_use_tap");
          break;
        default:
          throw new IllegalArgumentException("unknown_command: " + cmd);
      }
      return result.toString();
    } catch (Throwable t) {
      return json("ok", false, "error", message(t), "displayId", id).toString();
    } finally {
      Binder.restoreCallingIdentity(identity);
    }
  }

  byte[] imageBytes(String format, int quality, int maxWidth) throws Exception {
    Bitmap copy;
    synchronized (frameLock) {
      if (frame == null && id >= 1) frameLock.wait(3000);
      if (frame == null) throw new IllegalStateException("no_frame");
      Bitmap cropped = Bitmap.createBitmap(frame, 0, 0, frameWidth, frameHeight);
      copy = cropped.copy(Bitmap.Config.ARGB_8888, false);
      if (cropped != frame) cropped.recycle();
    }
    try {
      if (maxWidth > 0 && maxWidth < copy.getWidth()) {
        Bitmap small =
            Bitmap.createScaledBitmap(
                copy, maxWidth, Math.max(1, copy.getHeight() * maxWidth / copy.getWidth()), true);
        copy.recycle();
        copy = small;
      }
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      boolean jpeg = "jpeg".equals(format) || "jpg".equals(format);
      if (!jpeg && !"png".equals(format))
        throw new IllegalArgumentException("format_must_be_png_or_jpeg");
      copy.compress(
          jpeg ? Bitmap.CompressFormat.JPEG : Bitmap.CompressFormat.PNG,
          Math.max(1, Math.min(100, quality)),
          out);
      return out.toByteArray();
    } finally {
      copy.recycle();
    }
  }

  @Override
  public ParcelFileDescriptor capture(String format, int quality, int maxWidth) {
    authorize();
    try {
      byte[] bytes = imageBytes(format, quality, maxWidth);
      ParcelFileDescriptor[] pipe = ParcelFileDescriptor.createPipe();
      clients.execute(
          () -> {
            try (OutputStream out = new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])) {
              out.write(bytes);
            } catch (IOException ignored) {
            }
          });
      return pipe[0];
    } catch (Exception e) {
      throw new IllegalStateException(message(e));
    }
  }

  private void acceptLoop() {
    while (!closed)
      try {
        LocalSocket socket = server.accept();
        socket.setSoTimeout(15000);
        int uid = socket.getPeerCredentials().getUid();
        if (uid != 0 && uid != 2000 && uid != appUid) {
          socket.close();
          continue;
        }
        try {
          clients.execute(() -> serve(socket));
        } catch (RejectedExecutionException e) {
          socket.close();
        }
      } catch (IOException e) {
        if (!closed) android.util.Log.e("GhostDisplay", "socket", e);
      }
  }

  static String readLine(InputStream in) throws IOException {
    ByteArrayOutputStream b = new ByteArrayOutputStream();
    int c;
    while ((c = in.read()) != -1 && c != '\n') {
      if (b.size() >= 262144) throw new IOException("request_too_large");
      b.write(c);
    }
    return b.toString("UTF-8");
  }

  private void serve(LocalSocket socket) {
    try (LocalSocket s = socket) {
      OutputStream out = s.getOutputStream();
      try {
        JSONObject q = new JSONObject(readLine(s.getInputStream()));
        if ("screenshot".equals(q.optString("command"))) {
          String fmt = q.optString("format", "png");
          byte[] b = imageBytes(fmt, q.optInt("quality", 80), q.optInt("maxWidth", 0));
          out.write(
              (json(
                          "ok",
                          true,
                          "mime",
                          fmt.equals("png") ? "image/png" : "image/jpeg",
                          "byteLength",
                          b.length,
                          "displayId",
                          id,
                          "frameSequence",
                          frameSequence)
                      + "\n")
                  .getBytes(StandardCharsets.UTF_8));
          out.write(b);
        } else out.write((command(q.toString()) + "\n").getBytes(StandardCharsets.UTF_8));
      } catch (Throwable e) {
        out.write((json("ok", false, "error", message(e)) + "\n").getBytes(StandardCharsets.UTF_8));
      }
      out.flush();
    } catch (IOException ignored) {
    }
  }

  static String run(String... args) throws Exception {
    java.lang.Process p = new ProcessBuilder(args).redirectErrorStream(true).start();
    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
    Thread drain =
        new Thread(
            () -> {
              try (InputStream in = p.getInputStream()) {
                byte[] b = new byte[8192];
                int n;
                while ((n = in.read(b)) != -1) if (bytes.size() < 2000000) bytes.write(b, 0, n);
              } catch (IOException ignored) {
              }
            });
    drain.start();
    if (!p.waitFor(12, TimeUnit.SECONDS)) {
      p.destroyForcibly();
      throw new IOException("command_timeout");
    }
    drain.join(2000);
    String text = bytes.toString("UTF-8");
    if (p.exitValue() != 0) throw new IOException("exit_" + p.exitValue() + ": " + text);
    return text;
  }

  @Override
  public String startDisplay(int w, int h, int d) {
    return command(json("command", "start", "width", w, "height", h, "density", d).toString());
  }

  @Override
  public String stopDisplay() {
    return command("{\"command\":\"stop\"}");
  }

  @Override
  public String getStatus() {
    return command("{\"command\":\"status\"}");
  }

  @Override
  public int getDisplayId() {
    authorize();
    return id;
  }

  @Override
  public String screenshot(String path) {
    authorize();
    try (FileOutputStream out = new FileOutputStream(path)) {
      out.write(imageBytes("png", 100, 0));
      return json("ok", true, "path", path).toString();
    } catch (Exception e) {
      return json("ok", false, "error", message(e)).toString();
    }
  }

  @Override
  public String openApp(String p) {
    return command(json("command", "open-app", "package", p).toString());
  }

  @Override
  public String openComponent(String c) {
    return command(json("command", "open-component", "component", c).toString());
  }

  @Override
  public String openUrl(String u) {
    return command(json("command", "open-url", "url", u).toString());
  }

  @Override
  public String tap(int x, int y) {
    return command(json("command", "tap", "x", x, "y", y).toString());
  }

  @Override
  public String swipe(int x, int y, int a, int b, int ms) {
    return command(
        json("command", "swipe", "x1", x, "y1", y, "x2", a, "y2", b, "duration", ms).toString());
  }

  @Override
  public String setPanelPower(boolean on) {
    return json("ok", false, "error", "physical_panel_control_removed_use_phone_power_button")
        .toString();
  }

  @Override
  public String setStayAwake(boolean on) {
    return json("ok", false, "error", "wake_locks_managed_by_display_lifecycle").toString();
  }

  @Override
  public synchronized void destroy() {
    authorize();
    closed = true;
    cleanup();
    try {
      virtualDevice.removeAssociation();
    } catch (Exception e) {
      android.util.Log.e("GhostDisplay", "Association cleanup failed", e);
    }
    try {
      server.close();
    } catch (IOException ignored) {
    }
    clients.shutdownNow();
    android.os.Process.killProcess(android.os.Process.myPid());
  }
}
