import android.content.Context;
import android.graphics.*;
import android.hardware.display.*;
import android.media.*;
import android.os.*;
import android.view.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.concurrent.Executor;

/** Disposable shell probe. No changes to Ghost or persistent device settings. */
public final class GhostDisplayExperiment {
  static volatile long sequence,lastFrame;
  static Bitmap bitmap;
  static VirtualDisplay display;
  static ImageReader reader;
  static Object device;
  static PowerManager.WakeLock cpu,screen;
  static long started;
  static String mode;
  static final Object lock=new Object();
  static Object invoke(Object target,String name,Class<?>[] types,Object... args) throws Exception {
    return target.getClass().getMethod(name,types).invoke(target,args);
  }
  static void cleanup() {
    if(display!=null)display.release();
    if(device!=null)try{invoke(device,"close",new Class<?>[0]);}catch(Exception ignored){}
    if(reader!=null)reader.close();
    if(screen!=null&&screen.isHeld())screen.release();
    if(cpu!=null&&cpu.isHeld())cpu.release();
    System.out.println("CLEANED");
  }
  public static void main(String[] args) throws Exception {
    if(android.os.Process.myUid()!=2000)throw new SecurityException("shell only");
    mode=args[0];int seconds=Integer.parseInt(args[1]);
    if(seconds<10||seconds>600)throw new IllegalArgumentException("10..600 seconds");
    Looper.prepareMainLooper();
    Class<?> at=Class.forName("android.app.ActivityThread");
    Object thread=at.getMethod("systemMain").invoke(null);
    Context system=(Context)at.getMethod("getSystemContext").invoke(thread);
    Context shell=system.createPackageContext("com.android.shell",Context.CONTEXT_IGNORE_SECURITY);
    Handler handler=new Handler(Looper.getMainLooper());
    started=SystemClock.elapsedRealtime();
    try {
      int flags=0;
      for(String name:new String[]{"OWN_CONTENT_ONLY","SUPPORTS_TOUCH","DESTROY_CONTENT_ON_REMOVAL","TRUSTED","ALWAYS_UNLOCKED","TOUCH_FEEDBACK_DISABLED","OWN_FOCUS","STEAL_TOP_FOCUS_DISABLED",mode.equals("vdm")?"DEVICE_DISPLAY_GROUP":"OWN_DISPLAY_GROUP"}){
        Field f=DisplayManager.class.getDeclaredField("VIRTUAL_DISPLAY_FLAG_"+name);f.setAccessible(true);flags|=f.getInt(null);
      }
      reader=ImageReader.newInstance(1200,1920,PixelFormat.RGBA_8888,3);
      reader.setOnImageAvailableListener(r->{try(Image im=r.acquireLatestImage()){
        if(im==null)return;
        synchronized(lock){
          Image.Plane p=im.getPlanes()[0];int w=p.getRowStride()/p.getPixelStride();
          if(bitmap==null)bitmap=Bitmap.createBitmap(w,im.getHeight(),Bitmap.Config.ARGB_8888);
          bitmap.copyPixelsFromBuffer(p.getBuffer());sequence++;lastFrame=SystemClock.elapsedRealtime();
        }
      }catch(Exception e){System.out.println("FRAME_ERROR "+e);}},handler);
      if(mode.equals("vdm")){
        Class<?> bc=Class.forName("android.companion.virtual.VirtualDeviceParams$Builder");Object builder=bc.getConstructor().newInstance();
        invoke(builder,"setName",new Class<?>[]{String.class},"Ghost disposable experiment");
        invoke(builder,"setLocalDeviceOnly",new Class<?>[]{boolean.class},false);
        invoke(builder,"setLockState",new Class<?>[]{int.class},1);
        Object params=invoke(builder,"build",new Class<?>[0]);
        Context wrapped=new android.content.ContextWrapper(shell){
          @Override public Context getApplicationContext(){return this;}
          @Override public String getOpPackageName(){return "com.android.shell";}
          @Override public android.content.AttributionSource getAttributionSource(){return new android.content.AttributionSource.Builder(2000).setPackageName("com.android.shell").build();}
        };
        System.out.println("VDM_ATTR "+wrapped.getAttributionSource()+" PARAMS "+params);
        Object binder=Class.forName("android.os.ServiceManager").getMethod("getService",String.class).invoke(null,"virtualdevice");
        Class<?> api=Class.forName("android.companion.virtual.IVirtualDeviceManager");
        Object service=Class.forName("android.companion.virtual.IVirtualDeviceManager$Stub").getMethod("asInterface",IBinder.class).invoke(null,binder);
        Object manager=Class.forName("android.companion.virtual.VirtualDeviceManager").getConstructor(api,Context.class).newInstance(service,wrapped);
        int association=args.length>2?Integer.parseInt(args[2]):0;
        device=invoke(manager,"createVirtualDevice",new Class<?>[]{int.class,params.getClass()},association,params);
        System.out.println("DEVICE_ID "+invoke(device,"getDeviceId",new Class<?>[0]));
        VirtualDisplayConfig config=new VirtualDisplayConfig.Builder("Ghost VDM Experiment",1200,1920,320).setFlags(flags).setSurface(reader.getSurface()).build();
        display=(VirtualDisplay)invoke(device,"createVirtualDisplay",new Class<?>[]{VirtualDisplayConfig.class,Executor.class,VirtualDisplay.Callback.class},config,(Executor)handler::post,null);
      }else{
        display=shell.getSystemService(DisplayManager.class).createVirtualDisplay("Ghost Regular Experiment",1200,1920,320,reader.getSurface(),flags);
      }
      if(display==null)throw new IllegalStateException("display null");
      int id=display.getDisplay().getDisplayId();
      if(id<1)throw new IllegalStateException("physical display refused");
      System.out.println("DISPLAY_ID "+id+" FLAGS "+flags+" PID "+android.os.Process.myPid());
      PowerManager pm=shell.getSystemService(PowerManager.class);
      cpu=pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"ghost-experiment:cpu");cpu.acquire(seconds*1000L);
      screen=(PowerManager.WakeLock)PowerManager.class.getDeclaredMethod("newWakeLock",int.class,String.class,int.class).invoke(pm,PowerManager.SCREEN_BRIGHT_WAKE_LOCK,"ghost-experiment:display",id);screen.acquire(seconds*1000L);
      handler.post(new Runnable(){public void run(){
        try{
          synchronized(lock){if(bitmap!=null){
            Bitmap cropped=Bitmap.createBitmap(bitmap,0,0,1200,1920);
            try(FileOutputStream out=new FileOutputStream("/data/local/tmp/ghost-experiment-"+mode+".png")){cropped.compress(Bitmap.CompressFormat.PNG,100,out);}
            if(cropped!=bitmap)cropped.recycle();
          }}
          System.out.println("SAMPLE elapsed="+(SystemClock.elapsedRealtime()-started)+" sequence="+sequence+" age="+(SystemClock.elapsedRealtime()-lastFrame)+" state="+display.getDisplay().getState());
        }catch(Exception e){System.out.println("SAMPLE_ERROR "+e);}
        handler.postDelayed(this,10000);
      }});
      handler.postDelayed(()->{cleanup();System.exit(0);},seconds*1000L);
      Looper.loop();
    } catch(Throwable e){e.printStackTrace();cleanup();System.exit(1);}
  }
}
