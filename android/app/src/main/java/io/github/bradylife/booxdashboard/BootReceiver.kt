package io.github.bradylife.booxdashboard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 開機或更新後，把 06:05 與 18:05 兩個鬧鐘都再排一次。 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        AlarmScheduler.schedule(context)
    }
}
