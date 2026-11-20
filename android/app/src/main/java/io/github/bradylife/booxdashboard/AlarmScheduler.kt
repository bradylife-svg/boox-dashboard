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
 * 每天兩次鬧鐘：約 06:05 與 18:05（裝置本地時間）。
 * 有精確鬧鐘權限才用 setExactAndAllowWhileIdle；否則或被系統拒絕時改為不精確鬧鐘。
 * 重新開機後由 [BootReceiver] 把兩個時間都再排一次。
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
        try {
            val appContext = context.applicationContext
            val alarmManager = appContext.getSystemService(AlarmManager::class.java) ?: return
            for (slot in slots) {
                scheduleSlot(appContext, alarmManager, slot)
            }
        } catch (error: Exception) {
            Log.w(TAG, "排程失敗", error)
        }
    }

    private fun scheduleSlot(context: Context, alarmManager: AlarmManager, slot: Slot) {
        try {
            val pending = pendingIntent(context, slot.requestCode)
            val triggerAt = nextTriggerMillis(slot.hour, slot.minute)
            if (canUseExact(alarmManager)) {
                try {
                    alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
                    Log.i(TAG, "已排程精確鬧鐘 ${slot.hour}:${slot.minute.toString().padStart(2, '0')}")
                    return
                } catch (error: SecurityException) {
                    Log.w(TAG, "沒有精確鬧鐘權限，改為一般鬧鐘", error)
                }
            }
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            Log.i(TAG, "已排程一般鬧鐘 ${slot.hour}:${slot.minute.toString().padStart(2, '0')}")
        } catch (error: Exception) {
            Log.w(TAG, "這個時段無法排程", error)
        }
    }

    private fun canUseExact(alarmManager: AlarmManager): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return true
        }
        return try {
            alarmManager.canScheduleExactAlarms()
        } catch (error: Exception) {
            Log.w(TAG, "無法查詢精確鬧鐘權限", error)
            false
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
