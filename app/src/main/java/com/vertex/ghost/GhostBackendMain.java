package com.vertex.ghost;

import android.content.Context;
import android.os.Looper;

/** USB development probe. Normal runtime is owned by Shizuku. */
public final class GhostBackendMain {
  public static void main(String[] args) throws Exception {
    if (args.length != 1 || !"--development-shell".equals(args[0]))
      throw new IllegalArgumentException("development flag required");
    Looper.prepareMainLooper();
    Class<?> c = Class.forName("android.app.ActivityThread");
    Object thread = c.getMethod("systemMain").invoke(null);
    Context context = (Context) c.getMethod("getSystemContext").invoke(thread);
    new GhostDisplayUserService(context);
    Looper.loop();
  }
}
