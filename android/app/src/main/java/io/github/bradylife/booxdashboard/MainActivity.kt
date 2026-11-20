package io.github.bradylife.booxdashboard

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlarmManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
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
import android.widget.FrameLayout
import android.widget.TextView

/**
 * 全螢幕電子紙看板。點一下重新載入，長按在網頁與 PNG 之間切換。
 * 沒有過場動畫；殘影請用 BOOX 的全刷清掉。
 */
class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var statusView: TextView
    private var pngMode: Boolean
        get() = prefs().getBoolean(PREF_PNG, false)
        set(value) {
            prefs().edit().putBoolean(PREF_PNG, value).apply()
        }
    private var pinnedError = false
    private val hideStatus = Runnable {
        if (!pinnedError) {
            statusView.visibility = View.GONE
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        enterImmersive()

        webView = WebView(this)
        configureWebView(webView)
        statusView = TextView(this).apply {
            setBackgroundColor(Color.WHITE)
            setTextColor(Color.BLACK)
            textSize = 22f
            setPadding(48, 36, 48, 24)
            visibility = View.GONE
        }
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.WHITE)
            keepScreenOn = true
            addView(
                webView,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT,
                ),
            )
            addView(
                statusView,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                ),
            )
        }
        setContentView(root)
        wireGestures()
        AlarmScheduler.schedule(this)
        maybeAskExactAlarm()
        loadDashboard()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_REFRESH, false)) {
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
        statusView.removeCallbacks(hideStatus)
        webView.stopLoading()
        super.onDestroy()
    }

    private fun prefs() = getSharedPreferences(PREFS, MODE_PRIVATE)

    private fun enterImmersive() {
        window.setDecorFitsSystemWindows(false)
        window.insetsController?.let { controller ->
            controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
            controller.systemBarsBehavior =
                WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
    private fun configureWebView(view: WebView) {
        view.setBackgroundColor(Color.WHITE)
        view.isVerticalScrollBarEnabled = false
        view.isHorizontalScrollBarEnabled = false
        view.overScrollMode = View.OVER_SCROLL_NEVER
        view.isHapticFeedbackEnabled = false
        view.settings.apply {
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
        view.setInitialScale(0)
        view.webViewClient = object : WebViewClient() {
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

    @SuppressLint("ClickableViewAccessibility")
    private fun wireGestures() {
        val detector = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent): Boolean = true

            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                loadDashboard()
                return true
            }

            override fun onLongPress(e: MotionEvent) {
                pngMode = !pngMode
                showStatus(
                    if (pngMode) getString(R.string.mode_png) else getString(R.string.mode_html),
                    sticky = false,
                )
                loadDashboard(keepStatus = true)
            }
        })
        webView.setOnTouchListener { _, event ->
            detector.onTouchEvent(event)
            true
        }
    }

    private fun loadDashboard(keepStatus: Boolean = false) {
        pinnedError = false
        if (!keepStatus) {
            statusView.removeCallbacks(hideStatus)
            statusView.visibility = View.GONE
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
            webView.loadDataWithBaseURL(HTML_URL, html, "text/html", "utf-8", null)
        } else {
            webView.loadUrl(
                "$HTML_URL?ts=$stamp",
                mapOf("Cache-Control" to "no-cache", "Pragma" to "no-cache"),
            )
        }
    }

    private fun showStatus(text: String, sticky: Boolean) {
        pinnedError = sticky
        statusView.text = text
        statusView.visibility = View.VISIBLE
        statusView.removeCallbacks(hideStatus)
        if (!sticky) {
            statusView.postDelayed(hideStatus, 2500)
        }
    }

    private fun maybeAskExactAlarm() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return
        }
        val alarmManager = getSystemService(AlarmManager::class.java)
        if (alarmManager.canScheduleExactAlarms()) {
            return
        }
        if (prefs().getBoolean(PREF_ASKED_EXACT, false)) {
            return
        }
        prefs().edit().putBoolean(PREF_ASKED_EXACT, true).apply()
        try {
            startActivity(
                Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM).apply {
                    data = Uri.parse("package:$packageName")
                },
            )
        } catch (_: ActivityNotFoundException) {
            // 部分系統沒有這個設定頁，鬧鐘會改走一般排程。
        }
    }

    companion object {
        const val EXTRA_REFRESH = "refresh"
        const val HTML_URL = "https://bradylife-svg.github.io/boox-dashboard/"
        const val PNG_URL = "https://bradylife-svg.github.io/boox-dashboard/dashboard.png"
        private const val PREFS = "dashboard"
        private const val PREF_PNG = "png"
        private const val PREF_ASKED_EXACT = "asked_exact"
    }
}
