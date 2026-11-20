package io.github.bradylife.booxdashboard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 開機或更新後，接上下一個 30 分鐘重新載入。 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        try {
            AlarmScheduler.schedule(context)
        } catch (_: Throwable) {
            // 開機廣播失敗不應讓系統把這個 App 判成停止運作。
        }
    }
}
