package io.github.bradylife.booxdashboard

import android.webkit.WebView
import android.widget.ImageView
import android.widget.TextView
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [31, 32])
class MainActivityLaunchTest {
    @Test
    fun launchesOnAndroid12() {
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        assertFalse(activity.isFinishing)
        assertNull(activity.findViewById<TextView>(R.id.crash_text))
        val web = activity.findViewById<WebView>(R.id.dashboard_web)
        val image = activity.findViewById<ImageView>(R.id.dashboard_image)
        assertTrue(web != null || image != null)
        AlarmScheduler.schedule(activity)
    }

    @Test
    fun nextLaunchShowsPreviousCrash() {
        val context = RuntimeEnvironment.getApplication()
        CrashGuard.record(context, IllegalStateException("測試當機"))
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        val text = activity.findViewById<TextView>(R.id.crash_text)
        assertNotNull(text)
        assertTrue(text.text.contains("測試當機"))
        assertNull(activity.findViewById<WebView>(R.id.dashboard_web))
    }
}
