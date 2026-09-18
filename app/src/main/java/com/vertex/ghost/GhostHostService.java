package com.vertex.ghost;

import android.app.*;
import android.content.*;
import android.os.*;
import java.util.concurrent.*;
import org.json.JSONObject;

/** Desired state lives in the app; privileged state lives in the Shizuku daemon. */
public class GhostHostService extends Service {
  static final Object LIFECYCLE = new Object();
  private ScheduledExecutorService worker;
  private String previous = "";

  static boolean desired(Context c) {
    return c.getSharedPreferences("ghost", 0).getBoolean("running", false);
  }

  static void desired(Context c, boolean value) {
    synchronized (LIFECYCLE) {
      c.getSharedPreferences("ghost", 0).edit().putBoolean("running", value).commit();
    }
  }

  static void start(Context c) {
    desired(c, true);
    c.startForegroundService(new Intent(c, GhostHostService.class));
  }

  static void stop(Context c) {
    desired(c, false);
    c.stopService(new Intent(c, GhostHostService.class));
  }

  private Notification notification(String text) {
    Intent i = new Intent(this, GhostViewerActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    PendingIntent show =
        PendingIntent.getActivity(
            this, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    return new Notification.Builder(this, "ghost-runtime")
        .setSmallIcon(android.R.drawable.ic_menu_view)
        .setContentTitle("Ghost Display")
        .setContentText(text)
        .setContentIntent(show)
        .setOngoing(true)
        .addAction(new Notification.Action.Builder(null, "Open viewer", show).build())
        .build();
  }

  @Override
  public void onCreate() {
    super.onCreate();
    NotificationManager nm = getSystemService(NotificationManager.class);
    nm.createNotificationChannel(
        new NotificationChannel(
            "ghost-runtime", "Ghost runtime", NotificationManager.IMPORTANCE_LOW));
    startForeground(73, notification("Connecting to Shizuku"));
    worker = Executors.newSingleThreadScheduledExecutor();
    worker.scheduleWithFixedDelay(this::recover, 0, 15, TimeUnit.SECONDS);
  }

  private void recover() {
    if (!desired(this)) {
      stopSelf();
      return;
    }
    String text;
    try {
      IGhostDisplayService s = GhostShizukuClient.bindBlocking(this, 11000);
      JSONObject state;
      synchronized (LIFECYCLE) {
        if (!desired(this)) return;
        state = new JSONObject(s.startDisplay(1200, 1920, 320));
      }
      text =
          state.optBoolean("ok")
              ? "Running invisibly · tap to view"
              : "Needs attention: " + state.optString("error");
    } catch (Exception e) {
      text = "Waiting for Shizuku · open viewer for status";
    }
    if (!text.equals(previous)) {
      previous = text;
      getSystemService(NotificationManager.class).notify(73, notification(text));
    }
  }

  @Override
  public int onStartCommand(Intent i, int flags, int startId) {
    if (!desired(this)) {
      stopSelf();
      return START_NOT_STICKY;
    }
    return START_STICKY;
  }

  @Override
  public void onDestroy() {
    if (worker != null) worker.shutdownNow();
    super.onDestroy();
  }

  @Override
  public IBinder onBind(Intent i) {
    return null;
  }
}
