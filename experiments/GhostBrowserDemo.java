import android.app.ActivityOptions;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Looper;

/** Opens a public page in Chrome's Custom Tab, without exposing the user's tab strip. */
public final class GhostBrowserDemo {
  public static void main(String[] args) throws Exception {
    if (android.os.Process.myUid() != 2000) throw new SecurityException("shell only");
    int display = Integer.parseInt(args[0]);
    if (display <= 0) throw new IllegalArgumentException("virtual display required");
    Uri uri = Uri.parse(args[1]);
    if (!"https".equals(uri.getScheme())) throw new IllegalArgumentException("https required");
    Looper.prepareMainLooper();
    Class<?> at = Class.forName("android.app.ActivityThread");
    Object thread = at.getMethod("systemMain").invoke(null);
    Context system = (Context) at.getMethod("getSystemContext").invoke(thread);
    Context shell = system.createPackageContext("com.android.shell", Context.CONTEXT_IGNORE_SECURITY);
    Intent intent = new Intent(Intent.ACTION_VIEW, uri).setPackage("com.android.chrome")
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
    Bundle extras = new Bundle();
    extras.putBinder("android.support.customtabs.extra.SESSION", null);
    intent.putExtras(extras);
    Object binder = Class.forName("android.os.ServiceManager").getMethod("getService", String.class)
        .invoke(null, "activity_task");
    Object manager = Class.forName("android.app.IActivityTaskManager$Stub")
        .getMethod("asInterface", android.os.IBinder.class).invoke(null, binder);
    java.lang.reflect.Method start = manager.getClass().getMethod("startActivity",
        Class.forName("android.app.IApplicationThread"), String.class, String.class, Intent.class,
        String.class, android.os.IBinder.class, String.class, int.class, int.class,
        Class.forName("android.app.ProfilerInfo"), Bundle.class);
    int result = (Integer) start.invoke(manager, null, "com.android.shell", null, intent, null,
        null, null, 0, 0, null, ActivityOptions.makeBasic().setLaunchDisplayId(display).toBundle());
    if (result < 0) throw new IllegalStateException("launch failed: " + result);
    System.out.println("Opened public browser view on display " + display);
  }
}
