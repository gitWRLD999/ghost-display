package com.vertex.ghost;

import android.content.*;

public class GhostBootReceiver extends BroadcastReceiver {
  @Override
  public void onReceive(Context c, Intent i) {
    if (GhostHostService.desired(c))
      try {
        GhostHostService.start(c);
      } catch (Exception ignored) {
      }
  }
}
