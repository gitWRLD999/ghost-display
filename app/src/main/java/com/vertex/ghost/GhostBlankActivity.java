package com.vertex.ghost;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class GhostBlankActivity extends Activity {
  @Override
  public void onCreate(Bundle saved) {
    super.onCreate(saved);
    TextView t = new TextView(this);
    t.setText("Ghost Display\n\nReady for an app. Open one with ghostctl.");
    t.setTextSize(24);
    t.setPadding(48, 80, 48, 48);
    setContentView(t);
  }
}
