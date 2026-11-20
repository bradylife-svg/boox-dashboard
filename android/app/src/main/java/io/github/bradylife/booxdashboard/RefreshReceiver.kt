package io.github.bradylife.booxdashboard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.PowerManager

/** 鬧鐘響時重新排程，並把看板叫到前景重新載入。 */
class RefreshReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        try {
            AlarmScheduler.schedule(context)
            val power = context.getSystemService(PowerManager::class.java) ?: return
            val wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "booxdashboard:refresh")
            wakeLock.acquire(15_000L)
            val launch = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP or
                    Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra(MainActivity.EXTRA_REFRESH, true)
            }
            context.startActivity(launch)
        } catch (_: Throwable) {
            // Android 12 可能禁止從背景開啟畫面。鬧鐘仍已重新排程。
        }
    }

    companion object {
        const val ACTION_REFRESH = "io.github.bradylife.booxdashboard.action.REFRESH"
        const val EXTRA_SLOT = "slot"
    }
}
