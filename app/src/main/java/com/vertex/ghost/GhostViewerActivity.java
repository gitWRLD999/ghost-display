package com.vertex.ghost;

import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.util.concurrent.*;
import org.json.*;
import rikka.shizuku.Shizuku;

/** An explicit, aspect-preserving window onto the independent ImageReader surface. */
public class GhostViewerActivity extends Activity {
  private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor();
  private TextView state;
  private Portal portal;
  private EditText text;
  private volatile boolean visible;
  private volatile IGhostDisplayService backend;
  private final Shizuku.OnRequestPermissionResultListener permission =
      (code, result) -> {
        if (result == PackageManager.PERMISSION_GRANTED) startGhost();
      };

  @Override
  public void onCreate(Bundle saved) {
    super.onCreate(saved);
    LinearLayout root = new LinearLayout(this);
    root.setOrientation(LinearLayout.VERTICAL);
    root.setBackgroundColor(0xff101820);
    root.setOnApplyWindowInsetsListener(
        (v, i) -> {
          android.graphics.Insets b =
              i.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
          v.setPadding(b.left, b.top, b.right, b.bottom);
          return i;
        });
    LinearLayout top = row();
    button(top, "Start", this::startGhost);
    button(top, "Stop", () -> send("stop"));
    button(top, "Rotate", () -> send("rotate"));
    button(top, "Hide", this::finish);
    root.addView(top);
    state = new TextView(this);
    state.setText("Ghost · connect with Start");
    state.setTextColor(0xffb9cbd4);
    state.setPadding(20, 8, 20, 8);
    root.addView(state);
    portal = new Portal();
    root.addView(portal, new LinearLayout.LayoutParams(-1, 0, 1));
    LinearLayout entry = row();
    text = new EditText(this);
    text.setHint("Type into Ghost");
    text.setSingleLine(true);
    entry.addView(text, new LinearLayout.LayoutParams(0, -2, 1));
    button(
        entry,
        "Send",
        () -> {
          String value = text.getText().toString();
          send("text", "text", value);
          text.setText("");
        });
    root.addView(entry);
    LinearLayout nav = row();
    button(nav, "Back", () -> send("back"));
    button(nav, "Home", () -> send("home"));
    button(nav, "Enter", () -> send("key", "keycode", "ENTER"));
    button(
        nav,
        "Test",
        () -> send("open-component", "component", "com.vertex.ghost/.GhostTestActivity"));
    root.addView(nav);
    setContentView(root);
    Shizuku.addRequestPermissionResultListener(permission);
    worker.scheduleWithFixedDelay(this::refresh, 0, 300, TimeUnit.MILLISECONDS);
    if (GhostHostService.desired(this))
      try {
        GhostHostService.start(this);
      } catch (Exception e) {
        status(e.toString());
      }
  }

  private LinearLayout row() {
    LinearLayout l = new LinearLayout(this);
    l.setOrientation(LinearLayout.HORIZONTAL);
    return l;
  }

  private void button(LinearLayout parent, String label, Runnable action) {
    Button b = new Button(this);
    b.setText(label);
    b.setTextSize(13);
    b.setMinWidth(0);
    b.setPadding(4, 0, 4, 0);
    parent.addView(b, new LinearLayout.LayoutParams(0, -2, 1));
    b.setOnClickListener(v -> action.run());
  }

  private void status(String value) {
    runOnUiThread(() -> state.setText(value));
  }

  private void startGhost() {
    try {
      if (!Shizuku.pingBinder()) {
        status("Start Shizuku, then tap Start here");
        return;
      }
      if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
        Shizuku.requestPermission(1001);
        return;
      }
      if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
          != PackageManager.PERMISSION_GRANTED)
        requestPermissions(new String[] {android.Manifest.permission.POST_NOTIFICATIONS}, 1002);
      GhostHostService.start(this);
      send("start");
    } catch (Exception e) {
      status(e.toString());
    }
  }

  private IGhostDisplayService service() throws Exception {
    if (backend == null || !backend.asBinder().isBinderAlive())
      backend = GhostShizukuClient.bindBlocking(this, 10000);
    return backend;
  }

  private void send(String cmd, Object... fields) {
    if (cmd.equals("stop")) GhostHostService.stop(this);
    worker.execute(
        () -> {
          try {
            JSONObject q = GhostDisplayUserService.json(fields);
            q.put("command", cmd);
            JSONObject result = new JSONObject(service().command(q.toString()));
            if (!result.optBoolean("ok")) status(result.optString("error"));
            if (cmd.equals("stop")) {
              GhostShizukuClient.disconnectAndDestroy(this);
              backend = null;
              runOnUiThread(
                  () -> {
                    portal.setFrame(null);
                    state.setText("Stopped");
                  });
            }
          } catch (Exception e) {
            backend = null;
            status(e.toString());
          }
        });
  }

  private void refresh() {
    if (!visible || !GhostHostService.desired(this)) return;
    try {
      IGhostDisplayService s = service();
      Bitmap bitmap;
      try (ParcelFileDescriptor pfd = s.capture("jpeg", 80, 0);
          ParcelFileDescriptor.AutoCloseInputStream in =
              new ParcelFileDescriptor.AutoCloseInputStream(pfd)) {
        bitmap = BitmapFactory.decodeStream(in);
      }
      if (bitmap != null)
        runOnUiThread(
            () -> {
              if (visible) {
                portal.setFrame(bitmap);
                state.setText(
                    "Ghost · "
                        + bitmap.getWidth()
                        + " × "
                        + bitmap.getHeight()
                        + " · tap or swipe to control");
              } else bitmap.recycle();
            });
    } catch (Exception e) {
      backend = null;
      status(e.getMessage() == null ? e.toString() : e.getMessage());
    }
  }

  @Override
  protected void onResume() {
    super.onResume();
    visible = true;
  }

  @Override
  protected void onPause() {
    visible = false;
    super.onPause();
  }

  @Override
  protected void onDestroy() {
    visible = false;
    worker.shutdownNow();
    Shizuku.removeRequestPermissionResultListener(permission);
    portal.setFrame(null);
    super.onDestroy();
  }

  private class Portal extends View {
    private Bitmap bitmap;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final RectF fit = new RectF();
    private float downX, downY;
    private long downTime;
    private boolean valid;

    Portal() {
      super(GhostViewerActivity.this);
      setBackgroundColor(Color.BLACK);
      setContentDescription("Ghost frame");
    }

    void setFrame(Bitmap b) {
      Bitmap old = bitmap;
      bitmap = b;
      if (old != null && old != b) old.recycle();
      invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
      super.onDraw(canvas);
      if (bitmap == null) return;
      float scale =
          Math.min(
              (float) getWidth() / bitmap.getWidth(), (float) getHeight() / bitmap.getHeight());
      float w = bitmap.getWidth() * scale, h = bitmap.getHeight() * scale;
      fit.set(
          (getWidth() - w) / 2, (getHeight() - h) / 2, (getWidth() + w) / 2, (getHeight() + h) / 2);
      canvas.drawBitmap(bitmap, null, fit, paint);
      setContentDescription(
          "Ghost frame "
              + bitmap.getWidth()
              + "x"
              + bitmap.getHeight()
              + " fit "
              + fit.toShortString());
    }

    private int mapX(float x) {
      return Math.max(
          0,
          Math.min(
              bitmap.getWidth() - 1, (int) ((x - fit.left) * bitmap.getWidth() / fit.width())));
    }

    private int mapY(float y) {
      return Math.max(
          0,
          Math.min(
              bitmap.getHeight() - 1, (int) ((y - fit.top) * bitmap.getHeight() / fit.height())));
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
      if (bitmap == null) return true;
      if (e.getActionMasked() == MotionEvent.ACTION_DOWN) {
        valid = fit.contains(e.getX(), e.getY());
        downX = e.getX();
        downY = e.getY();
        downTime = e.getEventTime();
        return true;
      }
      if (e.getActionMasked() == MotionEvent.ACTION_CANCEL) {
        valid = false;
        return true;
      }
      if (e.getActionMasked() == MotionEvent.ACTION_UP && valid) {
        int x = mapX(downX), y = mapY(downY), x2 = mapX(e.getX()), y2 = mapY(e.getY());
        int ms = (int) Math.min(5000, e.getEventTime() - downTime);
        if (Math.hypot(e.getX() - downX, e.getY() - downY) < 12)
          send(ms >= 500 ? "long-press" : "tap", "x", x, "y", y, "duration", ms);
        else send("swipe", "x1", x, "y1", y, "x2", x2, "y2", y2, "duration", Math.max(80, ms));
        valid = false;
        performClick();
        return true;
      }
      return true;
    }

    @Override
    public boolean performClick() {
      super.performClick();
      return true;
    }
  }
}
