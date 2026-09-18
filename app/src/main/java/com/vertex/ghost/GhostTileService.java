package com.vertex.ghost;

import android.app.PendingIntent;
import android.content.Intent;
import android.service.quicksettings.TileService;

public class GhostTileService extends TileService {
  @Override
  public void onClick() {
    super.onClick();
    Intent i = new Intent(this, GhostViewerActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    startActivityAndCollapse(
        PendingIntent.getActivity(
            this, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
  }
}
