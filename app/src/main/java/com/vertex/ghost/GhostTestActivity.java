package com.vertex.ghost;

import android.app.Activity;
import android.os.*;
import android.text.*;
import android.view.*;
import android.widget.*;
import java.io.*;

/** Deterministic dual-display fixture: changing timer, independent edit state and counter. */
public class GhostTestActivity extends Activity {
  private final Handler timer = new Handler(Looper.getMainLooper());
  private TextView clock, counter;
  private int clicks, holds;
  private EditText input;
  private ScrollView scroll;
  private final Runnable tick =
      new Runnable() {
        public void run() {
          clock.setText("Live seconds: " + SystemClock.elapsedRealtime() / 1000);
          saveState();
          timer.postDelayed(this, 1000);
        }
      };

  private void saveState() {
    if (input == null || scroll == null) return;
    try (FileWriter f =
        new FileWriter(
            new File(getFilesDir(), "test-display-" + getDisplay().getDisplayId() + ".json"))) {
      f.write(
          GhostDisplayUserService.json(
                  "displayId",
                  getDisplay().getDisplayId(),
                  "text",
                  input.getText().toString(),
                  "clicks",
                  clicks,
                  "longPresses",
                  holds,
                  "scrollY",
                  scroll.getScrollY(),
                  "seconds",
                  SystemClock.elapsedRealtime() / 1000)
              .toString());
    } catch (IOException ignored) {
    }
  }

  @Override
  public void onCreate(Bundle b) {
    super.onCreate(b);
    LinearLayout root = new LinearLayout(this);
    root.setOrientation(1);
    root.setPadding(24, 40, 24, 24);
    root.setBackgroundColor(0xff153046);
    TextView title = new TextView(this);
    title.setText("Ghost test · display " + getDisplay().getDisplayId());
    title.setTextSize(26);
    root.addView(title);
    clock = new TextView(this);
    clock.setTextSize(22);
    root.addView(clock);
    input = new EditText(this);
    input.setId(1001);
    input.setSingleLine(true);
    input.setHint("Independent text field");
    input.setShowSoftInputOnFocus(false);
    root.addView(input);
    if (b != null) {
      clicks = b.getInt("clicks");
      holds = b.getInt("holds");
    }
    input.addTextChangedListener(
        new TextWatcher() {
          public void beforeTextChanged(CharSequence s, int st, int c, int a) {}

          public void onTextChanged(CharSequence s, int st, int before, int count) {
            saveState();
          }

          public void afterTextChanged(Editable e) {}
        });
    counter = new TextView(this);
    counter.setTextSize(24);
    root.addView(counter);
    Button add = new Button(this);
    add.setText("Add one");
    add.setOnClickListener(
        v -> {
          clicks++;
          counter.setText("Taps: " + clicks);
          saveState();
        });
    add.setOnLongClickListener(
        v -> {
          holds++;
          counter.setText("Long presses: " + holds);
          saveState();
          return true;
        });
    root.addView(add);
    counter.setText("Taps: " + clicks);
    scroll = new ScrollView(this);
    scroll.setId(1002);
    scroll.setOnScrollChangeListener((View v, int x, int y, int oldX, int oldY) -> saveState());
    LinearLayout rows = new LinearLayout(this);
    rows.setOrientation(1);
    for (int n = 1; n <= 40; n++) {
      TextView item = new TextView(this);
      item.setText("Scroll row " + n);
      item.setTextSize(20);
      item.setPadding(16, 20, 16, 20);
      rows.addView(item);
    }
    scroll.addView(rows);
    root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
    setContentView(root);
    input.requestFocus();
    timer.post(tick);
  }

  @Override
  protected void onDestroy() {
    timer.removeCallbacks(tick);
    super.onDestroy();
  }

  @Override
  protected void onSaveInstanceState(Bundle state) {
    state.putInt("clicks", clicks);
    state.putInt("holds", holds);
    super.onSaveInstanceState(state);
  }
}
