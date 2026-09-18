package com.vertex.ghost;

import android.content.*;
import org.json.*;

/** Protected by INTERACT_ACROSS_USERS_FULL in the manifest. No accessibility fallback. */
public class GhostCommandReceiver extends BroadcastReceiver {
  @Override
  public void onReceive(Context c, Intent intent) {
    PendingResult pending = goAsync();
    new Thread(
            () -> {
              try {
                String action = intent.getAction();
                if (action == null) throw new IllegalArgumentException("missing_action");
                action = action.substring(action.lastIndexOf('.') + 1);
                if (action.equals("HEADLESS_START")) GhostHostService.start(c);
                if (action.equals("HEADLESS_STOP")) GhostHostService.stop(c);
                IGhostDisplayService s = GhostShizukuClient.bindBlocking(c, 11000);
                String response;
                JSONObject q = new JSONObject();
                switch (action) {
                  case "HEADLESS_START":
                    response =
                        s.startDisplay(
                            intent.getIntExtra("width", 1200),
                            intent.getIntExtra("height", 1920),
                            intent.getIntExtra("density", 320));
                    break;
                  case "HEADLESS_STOP":
                    response = s.stopDisplay();
                    GhostShizukuClient.disconnectAndDestroy(c);
                    break;
                  case "HEADLESS_SCREENSHOT":
                    response =
                        s.screenshot(
                            intent.getStringExtra("path") == null
                                ? "/data/local/tmp/ghost.png"
                                : intent.getStringExtra("path"));
                    break;
                  default:
                    String cmd;
                    switch (action) {
                      case "HEADLESS_STATUS":
                      case "STATUS":
                        cmd = "status";
                        break;
                      case "OPEN_APP":
                        cmd = "open-app";
                        q.put("package", intent.getStringExtra("pkg"));
                        break;
                      case "OPEN_COMPONENT":
                        cmd = "open-component";
                        q.put("component", intent.getStringExtra("component"));
                        break;
                      case "OPEN_URL":
                        cmd = "open-url";
                        q.put("url", intent.getStringExtra("url"));
                        break;
                      case "SET_TEXT":
                        cmd = "text";
                        q.put("text", intent.getStringExtra("text"));
                        break;
                      case "CLICK":
                        cmd = "tap";
                        q.put("x", intent.getIntExtra("x", -1));
                        q.put("y", intent.getIntExtra("y", -1));
                        break;
                      case "SWIPE":
                        cmd = "swipe";
                        for (String k : new String[] {"x1", "y1", "x2", "y2"})
                          q.put(k, intent.getIntExtra(k, -1));
                        q.put("duration", intent.getIntExtra("duration", 350));
                        break;
                      case "FOCUS":
                        cmd = "focus";
                        break;
                      case "DUMP":
                        cmd = "dump";
                        break;
                      default:
                        throw new IllegalArgumentException("unsupported_action: " + action);
                    }
                    q.put("command", cmd);
                    response = s.command(q.toString());
                }
                pending.setResultCode(new JSONObject(response).optBoolean("ok") ? 0 : 1);
                pending.setResultData(response);
              } catch (Exception e) {
                pending.setResultCode(1);
                pending.setResultData(
                    GhostDisplayUserService.json("ok", false, "error", e.toString()).toString());
              } finally {
                pending.finish();
              }
            },
            "ghost-broadcast")
        .start();
  }
}
