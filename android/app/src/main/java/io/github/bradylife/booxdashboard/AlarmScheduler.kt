package io.github.bradylife.booxdashboard

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * 每天兩次精確鬧鐘：約 06:05 與 18:05（裝置本地時間）。
 * 每次排程都會把兩個時間都再排一次，重新開機後由 [BootReceiver] 呼叫。
 */
object AlarmScheduler {
    private const val TAG = "BooxAlarm"
    const val SLOT_MORNING = 605
    const val SLOT_EVENING = 1805

    private data class Slot(val requestCode: Int, val hour: Int, val minute: Int)

    private val slots = listOf(
        Slot(SLOT_MORNING, 6, 5),
        Slot(SLOT_EVENING, 18, 5),
    )

    fun schedule(context: Context) {
        val appContext = context.applicationContext
        val alarmManager = appContext.getSystemService(AlarmManager::class.java)
        for (slot in slots) {
            scheduleSlot(appContext, alarmManager, slot)
        }
    }

    private fun scheduleSlot(context: Context, alarmManager: AlarmManager, slot: Slot) {
        val pending = pendingIntent(context, slot.requestCode)
        val triggerAt = nextTriggerMillis(slot.hour, slot.minute)
        try {
            val canExact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
                alarmManager.canScheduleExactAlarms()
            if (canExact) {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            } else {
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            }
            Log.i(TAG, "已排程 ${slot.hour}:${slot.minute.toString().padStart(2, '0')} exact=$canExact")
        } catch (error: SecurityException) {
            Log.w(TAG, "無法使用精確鬧鐘，改為一般鬧鐘", error)
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
        }
    }

    private fun pendingIntent(context: Context, requestCode: Int): PendingIntent {
        val intent = Intent(context, RefreshReceiver::class.java).apply {
            action = RefreshReceiver.ACTION_REFRESH
            putExtra(RefreshReceiver.EXTRA_SLOT, requestCode)
        }
        return PendingIntent.getBroadcast(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    /** 下一個尚未過去的本地時間。已過則排到明天同一時刻。 */
    fun nextTriggerMillis(hour: Int, minute: Int, now: ZonedDateTime = ZonedDateTime.now(ZoneId.systemDefault())): Long {
        var next = now.withHour(hour).withMinute(minute).withSecond(0).withNano(0)
        if (!next.isAfter(now)) {
            next = next.plusDays(1)
        }
        return next.toInstant().toEpochMilli()
    }
}
