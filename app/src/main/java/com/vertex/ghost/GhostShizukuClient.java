package com.vertex.ghost;

import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import rikka.shizuku.Shizuku;

/** One cached binding per app process; retries never accumulate service connections. */
public final class GhostShizukuClient {
  public static final int VERSION = 8;
  private static final Object LOCK = new Object();
  private static final Handler MAIN = new Handler(Looper.getMainLooper());
  private static IGhostDisplayService service;
  private static ServiceConnection connection;
  private static long bindingAt;

  public interface Callback {
    void onService(IGhostDisplayService svc);

    void onError(String error);
  }

  public static Shizuku.UserServiceArgs serviceArgs(Context ctx) {
    return new Shizuku.UserServiceArgs(
            new ComponentName(ctx.getPackageName(), GhostDisplayUserService.class.getName()))
        .daemon(true)
        .processNameSuffix("ghost_display")
        .tag("ghost-display")
        .version(VERSION);
  }

  private static void connect(Context ctx) {
    synchronized (LOCK) {
      if (service != null && service.asBinder().isBinderAlive()) return;
      if (connection != null && SystemClock.elapsedRealtime() - bindingAt < 15000) return;
      if (connection != null)
        try {
          Shizuku.unbindUserService(serviceArgs(ctx), connection, false);
        } catch (Throwable ignored) {
        }
      connection =
          new ServiceConnection() {
            public void onServiceConnected(ComponentName n, IBinder b) {
              synchronized (LOCK) {
                service = IGhostDisplayService.Stub.asInterface(b);
                LOCK.notifyAll();
              }
            }

            public void onServiceDisconnected(ComponentName n) {
              synchronized (LOCK) {
                service = null;
                bindingAt = 0;
                LOCK.notifyAll();
              }
            }
          };
      bindingAt = SystemClock.elapsedRealtime();
      try {
        Shizuku.bindUserService(serviceArgs(ctx), connection);
      } catch (Throwable e) {
        connection = null;
        LOCK.notifyAll();
      }
    }
  }

  public static IGhostDisplayService bindBlocking(Context context, long timeout) throws Exception {
    if (Looper.myLooper() == Looper.getMainLooper())
      throw new IllegalStateException("bind_on_worker_thread_only");
    if (!Shizuku.pingBinder()) throw new IllegalStateException("shizuku_not_running");
    if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED)
      throw new IllegalStateException("shizuku_permission_missing_open_viewer");
    Context ctx = context.getApplicationContext();
    MAIN.post(() -> connect(ctx));
    long end = SystemClock.elapsedRealtime() + timeout;
    synchronized (LOCK) {
      while (service == null || !service.asBinder().isBinderAlive()) {
        long left = end - SystemClock.elapsedRealtime();
        if (left <= 0) throw new IllegalStateException("shizuku_bind_timeout");
        LOCK.wait(left);
      }
      return service;
    }
  }

  public static void bind(Context ctx, Callback cb) {
    new Thread(
            () -> {
              try {
                cb.onService(bindBlocking(ctx, 12000));
              } catch (Exception e) {
                cb.onError(e.toString());
              }
            },
            "ghost-bind")
        .start();
  }

  public static void disconnectAndDestroy(Context ctx) {
    MAIN.post(
        () -> {
          synchronized (LOCK) {
            try {
              Shizuku.unbindUserService(serviceArgs(ctx), connection, true);
            } catch (Throwable ignored) {
            }
            service = null;
            connection = null;
            bindingAt = 0;
          }
        });
  }
}
