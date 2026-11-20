package io.github.bradylife.booxdashboard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 開機或更新後，把 06:05 與 18:05 兩個鬧鐘都再排一次。 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        try {
            AlarmScheduler.schedule(context)
        } catch (_: Throwable) {
            // 開機廣播失敗不應讓系統把這個 App 判成停止運作。
        }
    }
}
