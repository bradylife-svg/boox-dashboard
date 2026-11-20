package io.github.bradylife.booxdashboard

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlarmManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.net.HttpURLConnection
import java.net.URL

/**
 * 全螢幕電子紙看板。點一下重新載入，長按在網頁與 PNG 之間切換。
 * 硬體加速關掉：BOOX 的 WebView 在硬體加速下常於建立當下就原生崩潰。
 */
class MainActivity : Activity() {
    private var webView: WebView? = null
    private var imageView: ImageView? = null
    private var statusView: TextView? = null
    private var pinnedError = false
    private val hideStatus = Runnable {
        if (!pinnedError) {
            statusView?.visibility = View.GONE
        }
    }
    private var pngMode: Boolean
        get() = prefs().getBoolean(PREF_PNG, false)
        set(value) {
            prefs().edit().putBoolean(PREF_PNG, value).apply()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } catch (error: Throwable) {
            Log.w(TAG, "無法設定螢幕鎖定顯示", error)
        }

        if (!intent.getBooleanExtra(EXTRA_IGNORE_CRASH, false)) {
            val previous = try {
                CrashGuard.read(this)
            } catch (error: Throwable) {
                Log.w(TAG, "無法讀取崩潰記錄", error)
                null
            }
            if (!previous.isNullOrBlank()) {
                showCrashReport(previous)
                return
            }
        }

        try {
            startDashboard()
        } catch (error: Throwable) {
            Log.e(TAG, "啟動失敗", error)
            try {
                CrashGuard.record(this, error)
            } catch (writeError: Throwable) {
                Log.e(TAG, "無法寫入崩潰記錄", writeError)
            }
            showCrashReport(error.stackTraceToString())
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_REFRESH, false) && (webView != null || imageView != null)) {
            loadDashboard()
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            enterImmersive()
        }
    }

    override fun onDestroy() {
        statusView?.removeCallbacks(hideStatus)
        webView?.apply {
            stopLoading()
            destroy()
        }
        webView = null
        super.onDestroy()
    }

    private fun startDashboard() {
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.WHITE)
            keepScreenOn = true
        }
        val created = createWebView()
        if (created != null) {
            webView = created
            root.addView(
                created,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT,
                ),
            )
        } else {
            val image = ImageView(this).apply {
                id = R.id.dashboard_image
                setBackgroundColor(Color.WHITE)
                scaleType = ImageView.ScaleType.FIT_CENTER
                contentDescription = getString(R.string.app_name)
            }
            imageView = image
            root.addView(
                image,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT,
                ),
            )
            pngMode = true
        }
        val status = TextView(this).apply {
            setBackgroundColor(Color.WHITE)
            setTextColor(Color.BLACK)
            textSize = 22f
            setPadding(48, 36, 48, 24)
            visibility = View.GONE
        }
        statusView = status
        root.addView(
            status,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
            ),
        )
        setContentView(root)
        enterImmersive()
        try {
            window.decorView.setForceDarkAllowed(false)
        } catch (error: Throwable) {
            Log.w(TAG, "無法關閉強制深色", error)
        }
        wireGestures()
        try {
            AlarmScheduler.schedule(this)
        } catch (error: Throwable) {
            Log.w(TAG, "排程失敗", error)
        }
        maybeAskExactAlarm()
        if (created == null) {
            showStatus(getString(R.string.webview_unavailable), sticky = true)
        }
        loadDashboard()
    }

    private fun showCrashReport(text: String) {
        val title = TextView(this).apply {
            setTextColor(Color.BLACK)
            textSize = 28f
            setText(R.string.crash_title)
        }
        val hint = TextView(this).apply {
            setTextColor(Color.BLACK)
            textSize = 18f
            setPadding(0, 16, 0, 16)
            setText(R.string.crash_hint)
        }
        val body = TextView(this).apply {
            id = R.id.crash_text
            setTextColor(Color.BLACK)
            textSize = 16f
            this.text = text
        }
        val retry = Button(this).apply {
            id = R.id.crash_retry
            setText(R.string.crash_retry)
            setOnClickListener {
                try {
                    CrashGuard.clear(this@MainActivity)
                } catch (error: Throwable) {
                    Log.w(TAG, "無法清除崩潰記錄", error)
                }
                val restart = Intent(this@MainActivity, MainActivity::class.java).apply {
                    putExtra(EXTRA_IGNORE_CRASH, true)
                }
                startActivity(restart)
                finish()
            }
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(48, 48, 48, 48)
            addView(title)
            addView(hint)
            addView(retry)
            addView(body)
        }
        val scroll = ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            addView(column)
        }
        setContentView(scroll)
    }

    private fun prefs() = getSharedPreferences(PREFS, MODE_PRIVATE)

    private fun enterImmersive() {
        try {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior =
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } catch (error: Throwable) {
            Log.w(TAG, "無法進入全螢幕", error)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView(): WebView? {
        return try {
            WebView(this).apply {
                id = R.id.dashboard_web
                setBackgroundColor(Color.WHITE)
                isVerticalScrollBarEnabled = false
                isHorizontalScrollBarEnabled = false
                overScrollMode = View.OVER_SCROLL_NEVER
                isHapticFeedbackEnabled = false
                setLayerType(View.LAYER_TYPE_SOFTWARE, null)
                settings.apply {
                    javaScriptEnabled = false
                    domStorageEnabled = false
                    cacheMode = WebSettings.LOAD_NO_CACHE
                    useWideViewPort = true
                    loadWithOverviewMode = true
                    setSupportZoom(false)
                    builtInZoomControls = false
                    displayZoomControls = false
                    mediaPlaybackRequiresUserGesture = true
                    textZoom = 100
                    loadsImagesAutomatically = true
                    mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                }
                setInitialScale(0)
                webViewClient = object : WebViewClient() {
                    override fun onReceivedError(
                        view: WebView,
                        request: WebResourceRequest,
                        error: WebResourceError,
                    ) {
                        if (request.isForMainFrame || pngMode) {
                            showStatus(getString(R.string.load_failed), sticky = true)
                        }
                    }
                }
            }
        } catch (error: Throwable) {
            Log.e(TAG, "WebView 無法建立", error)
            null
        }
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun wireGestures() {
        val detector = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent): Boolean = true

            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                loadDashboard()
                return true
            }

            override fun onLongPress(e: MotionEvent) {
                if (webView == null) {
                    loadDashboard()
                    return
                }
                pngMode = !pngMode
                showStatus(
                    if (pngMode) getString(R.string.mode_png) else getString(R.string.mode_html),
                    sticky = false,
                )
                loadDashboard(keepStatus = true)
            }
        })
        val listener = View.OnTouchListener { _, event ->
            detector.onTouchEvent(event)
            true
        }
        webView?.setOnTouchListener(listener)
        imageView?.setOnTouchListener(listener)
    }

    private fun loadDashboard(keepStatus: Boolean = false) {
        try {
            pinnedError = false
            if (!keepStatus) {
                statusView?.removeCallbacks(hideStatus)
                statusView?.visibility = View.GONE
            }
            val page = webView
            if (page == null) {
                imageView?.let { loadPngInto(it) }
                return
            }
            val stamp = System.currentTimeMillis()
            if (pngMode) {
                val image = "$PNG_URL?ts=$stamp"
                val html = """
                    <!DOCTYPE html>
                    <html lang="zh-Hant-TW"><head>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=1860, height=2480, initial-scale=1, user-scalable=no">
                    <style>
                      html,body{margin:0;padding:0;background:#fff;width:1860px;height:2480px;overflow:hidden;}
                      img{width:1860px;height:2480px;display:block;}
                    </style></head>
                    <body><img src="$image" alt="晨間看板"></body></html>
                """.trimIndent()
                page.loadDataWithBaseURL(HTML_URL, html, "text/html", "utf-8", null)
            } else {
                page.loadUrl(
                    "$HTML_URL?ts=$stamp",
                    mapOf("Cache-Control" to "no-cache", "Pragma" to "no-cache"),
                )
            }
        } catch (error: Throwable) {
            Log.e(TAG, "載入看板失敗", error)
            showStatus(getString(R.string.load_failed), sticky = true)
        }
    }

    private fun loadPngInto(image: ImageView) {
        Thread {
            try {
                val connection = URL("$PNG_URL?ts=${System.currentTimeMillis()}").openConnection() as HttpURLConnection
                connection.connectTimeout = 15_000
                connection.readTimeout = 20_000
                connection.setRequestProperty("Cache-Control", "no-cache")
                val bitmap = connection.inputStream.use { BitmapFactory.decodeStream(it) }
                connection.disconnect()
                runOnUiThread {
                    if (isDestroyed) {
                        return@runOnUiThread
                    }
                    if (bitmap != null) {
                        image.setImageBitmap(bitmap)
                    } else {
                        showStatus(getString(R.string.load_failed), sticky = true)
                    }
                }
            } catch (error: Throwable) {
                Log.w(TAG, "圖片下載失敗", error)
                runOnUiThread {
                    if (!isDestroyed) {
                        showStatus(getString(R.string.load_failed), sticky = true)
                    }
                }
            }
        }.start()
    }

    private fun showStatus(text: String, sticky: Boolean) {
        val view = statusView ?: return
        pinnedError = sticky
        view.text = text
        view.visibility = View.VISIBLE
        view.removeCallbacks(hideStatus)
        if (!sticky) {
            view.postDelayed(hideStatus, 2500)
        }
    }

    private fun maybeAskExactAlarm() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return
        }
        try {
            val alarmManager = getSystemService(AlarmManager::class.java) ?: return
            if (alarmManager.canScheduleExactAlarms()) {
                return
            }
            if (prefs().getBoolean(PREF_ASKED_EXACT, false)) {
                return
            }
            prefs().edit().putBoolean(PREF_ASKED_EXACT, true).commit()
            startActivity(
                Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM).apply {
                    data = Uri.parse("package:$packageName")
                },
            )
        } catch (error: ActivityNotFoundException) {
            Log.w(TAG, "沒有精確鬧鐘設定頁", error)
        } catch (error: Throwable) {
            Log.w(TAG, "無法開啟精確鬧鐘設定", error)
        }
    }

    companion object {
        private const val TAG = "BooxDashboard"
        const val EXTRA_REFRESH = "refresh"
        const val EXTRA_IGNORE_CRASH = "ignore_crash"
        const val HTML_URL = "https://bradylife-svg.github.io/boox-dashboard/"
        const val PNG_URL = "https://bradylife-svg.github.io/boox-dashboard/dashboard.png"
        private const val PREFS = "dashboard"
        private const val PREF_PNG = "png"
        private const val PREF_ASKED_EXACT = "asked_exact"
    }
}
