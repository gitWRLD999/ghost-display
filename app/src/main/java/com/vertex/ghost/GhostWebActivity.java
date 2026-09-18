package com.vertex.ghost;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class GhostWebActivity extends Activity {
  @Override
  protected void onCreate(Bundle b) {
    super.onCreate(b);
    WebView web = new WebView(this);
    setContentView(web);
    try {
      WebSettings s = web.getSettings();
      s.setJavaScriptEnabled(true);
      s.setDomStorageEnabled(true);
      s.setLoadWithOverviewMode(true);
      s.setUseWideViewPort(true);
      s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
    } catch (Throwable ignored) {
    }
    web.setWebViewClient(new WebViewClient());
    String url = getIntent().getStringExtra("url");
    if (url == null || url.length() == 0) url = "https://google.com";
    if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://" + url;
    web.loadUrl(url);
  }
}
