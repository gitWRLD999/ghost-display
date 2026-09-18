package com.vertex.ghost;

import android.companion.AssociationInfo;
import android.content.Context;
import android.hardware.display.VirtualDisplay;
import android.hardware.display.VirtualDisplayConfig;
import android.os.IBinder;
import android.system.Os;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Executor;
import org.json.JSONObject;

/** Owns the VirtualDevice and a dedicated, recoverable shell companion association. */
final class GhostVirtualDevice {
  private static final String OWNER = "com.android.shell";
  private static final String PROFILE = "android.app.role.COMPANION_DEVICE_APP_STREAMING";
  private final Context context;
  private final AtomicFile record;
  private Object device;
  private int deviceId = -1, associationId = -1;

  GhostVirtualDevice(Context context) {
    this.context = context;
    record = new AtomicFile(new File("/data/local/tmp/ghost-display/association-v1.json"));
  }

  private static Object call(Object target, String name, Class<?>[] types, Object... args)
      throws Exception {
    return target.getClass().getMethod(name, types).invoke(target, args);
  }

  private static Object service(String name, String type) throws Exception {
    Object binder =
        Class.forName("android.os.ServiceManager")
            .getMethod("getService", String.class)
            .invoke(null, name);
    if (binder == null) throw new IllegalStateException("missing_service: " + name);
    return Class.forName(type + "$Stub")
        .getMethod("asInterface", IBinder.class)
        .invoke(null, binder);
  }

  @SuppressWarnings("unchecked")
  private List<AssociationInfo> associations() throws Exception {
    return (List<AssociationInfo>)
        call(
            service("companiondevice", "android.companion.ICompanionDeviceManager"),
            "getAssociations",
            new Class<?>[] {String.class, int.class},
            OWNER,
            0);
  }

  private String address(boolean create) throws Exception {
    if (record.getBaseFile().exists() || new File(record.getBaseFile().getPath() + ".bak").exists()) {
      JSONObject saved = new JSONObject(new String(record.readFully(), StandardCharsets.UTF_8));
      String value = saved.getString("address");
      if (saved.getInt("version") != 1 || !value.matches("02(:[0-9a-f]{2}){5}"))
        throw new IllegalStateException("invalid_ghost_association_record");
      return value;
    }
    if (!create) return null;
    File directory = record.getBaseFile().getParentFile();
    if (!directory.isDirectory() && !directory.mkdirs())
      throw new IllegalStateException("cannot_create_association_record");
    Os.chmod(directory.getPath(), 0700);
    List<AssociationInfo> existing = associations();
    String value;
    boolean collision;
    do {
      byte[] random = new byte[5];
      new SecureRandom().nextBytes(random);
      StringBuilder address = new StringBuilder("02");
      for (byte b : random) address.append(String.format(Locale.ROOT, ":%02x", b & 255));
      value = address.toString();
      collision = false;
      for (AssociationInfo info : existing)
        if (value.equalsIgnoreCase(String.valueOf(info.getDeviceMacAddress()))) collision = true;
    } while (collision);
    // Persist before creating the association so a process crash can recover ownership.
    FileOutputStream output = record.startWrite();
    try {
      output.write(
          new JSONObject()
              .put("version", 1)
              .put("address", value)
              .toString()
              .getBytes(StandardCharsets.UTF_8));
      record.finishWrite(output);
    } catch (Exception e) {
      record.failWrite(output);
      throw e;
    }
    Os.chmod(record.getBaseFile().getPath(), 0600);
    return value;
  }

  private AssociationInfo find(String address) throws Exception {
    for (AssociationInfo info : associations()) {
      if (!address.equalsIgnoreCase(String.valueOf(info.getDeviceMacAddress()))) continue;
      if (!OWNER.equals(call(info, "getPackageName", new Class<?>[0]))
          || !PROFILE.equals(info.getDeviceProfile())
          || !info.isSelfManaged())
        throw new IllegalStateException("ghost_association_identity_mismatch");
      return info;
    }
    return null;
  }

  private int ensureAssociation() throws Exception {
    String address = address(true);
    AssociationInfo info = find(address);
    if (info == null) {
      GhostDisplayUserService.run(
          "/system/bin/cmd", "companiondevice", "associate", "0", OWNER, address, PROFILE, "true");
      info = find(address);
    }
    if (info == null) throw new IllegalStateException("ghost_association_not_created");
    associationId = info.getId();
    return associationId;
  }

  VirtualDisplay create(VirtualDisplayConfig config, Executor executor) throws Exception {
    int association = ensureAssociation();
    Class<?> builderClass = Class.forName("android.companion.virtual.VirtualDeviceParams$Builder");
    Object builder = builderClass.getConstructor().newInstance();
    call(builder, "setName", new Class<?>[] {String.class}, "Ghost Display");
    call(builder, "setLockState", new Class<?>[] {int.class}, 1);
    // Default is association-backed. Local-only devices are restricted to system_server.
    Object params = call(builder, "build", new Class<?>[0]);
    Class<?> api = Class.forName("android.companion.virtual.IVirtualDeviceManager");
    Object manager =
        Class.forName("android.companion.virtual.VirtualDeviceManager")
            .getConstructor(api, Context.class)
            .newInstance(service("virtualdevice", api.getName()), context);
    device =
        call(
            manager,
            "createVirtualDevice",
            new Class<?>[] {int.class, params.getClass()},
            association,
            params);
    deviceId = (Integer) call(device, "getDeviceId", new Class<?>[0]);
    return (VirtualDisplay)
        call(
            device,
            "createVirtualDisplay",
            new Class<?>[] {
              VirtualDisplayConfig.class, Executor.class, VirtualDisplay.Callback.class
            },
            config,
            executor,
            null);
  }

  int deviceId() {
    return deviceId;
  }

  int associationId() {
    return associationId;
  }

  void closeDevice() throws Exception {
    if (device != null) call(device, "close", new Class<?>[0]);
    device = null;
    deviceId = -1;
  }

  void removeAssociation() throws Exception {
    String address = address(false);
    if (address == null) return;
    if (find(address) != null) {
      GhostDisplayUserService.run(
          "/system/bin/cmd", "companiondevice", "disassociate", "0", OWNER, address);
      if (find(address) != null) throw new IllegalStateException("association_cleanup_failed");
    }
    record.delete();
    associationId = -1;
  }
}
