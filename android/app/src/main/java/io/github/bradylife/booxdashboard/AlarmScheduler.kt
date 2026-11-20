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
 * 一條精確鬧鐘，依序響在本地時間
 * 05:15–08:45 與 17:15–20:45，每 30 分鐘一次。
 * 響了就排下一個時段。重新開機後由 [BootReceiver] 再接上。
 */
object AlarmScheduler {
    private const val TAG = "BooxAlarm"
    private const val REQUEST_NEXT = 3015
    private val LEGACY_REQUESTS = intArrayOf(605, 1805)

    /** 本地時間的重新載入時段，依序排列。 */
    val RELOAD_SLOTS: List<Pair<Int, Int>> = listOf(
        5 to 15,
        5 to 45,
        6 to 15,
        6 to 45,
        7 to 15,
        7 to 45,
        8 to 15,
        8 to 45,
        17 to 15,
        17 to 45,
        18 to 15,
        18 to 45,
        19 to 15,
        19 to 45,
        20 to 15,
        20 to 45,
    )

    fun schedule(context: Context) {
        try {
            val appContext = context.applicationContext
            val alarmManager = appContext.getSystemService(AlarmManager::class.java) ?: return
            cancelLegacy(appContext, alarmManager)
            val triggerAt = nextReload(ZonedDateTime.now(ZoneId.systemDefault()))
            scheduleAt(appContext, alarmManager, triggerAt.toInstant().toEpochMilli(), triggerAt)
        } catch (error: Exception) {
            Log.w(TAG, "排程失敗", error)
        }
    }

    /** 下一個嚴格晚於現在約 30 秒的時段；今天沒有了就排到明天 05:15。 */
    fun nextReload(now: ZonedDateTime): ZonedDateTime {
        val earliest = now.plusSeconds(30)
        for ((hour, minute) in RELOAD_SLOTS) {
            val candidate = now.withHour(hour).withMinute(minute).withSecond(0).withNano(0)
            if (candidate.isAfter(earliest)) {
                return candidate
            }
        }
        val (hour, minute) = RELOAD_SLOTS.first()
        return now.plusDays(1).withHour(hour).withMinute(minute).withSecond(0).withNano(0)
    }

    private fun scheduleAt(
        context: Context,
        alarmManager: AlarmManager,
        triggerAt: Long,
        whenLocal: ZonedDateTime,
    ) {
        val pending = pendingIntent(context, REQUEST_NEXT)
        val label = "%02d:%02d".format(whenLocal.hour, whenLocal.minute)
        try {
            if (canUseExact(alarmManager)) {
                try {
                    alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
                    Log.i(TAG, "已排程精確鬧鐘 $label")
                    return
                } catch (error: SecurityException) {
                    Log.w(TAG, "沒有精確鬧鐘權限，改為一般鬧鐘", error)
                }
            }
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
            Log.i(TAG, "已排程一般鬧鐘 $label")
        } catch (error: Exception) {
            Log.w(TAG, "無法排程 $label", error)
        }
    }

    private fun cancelLegacy(context: Context, alarmManager: AlarmManager) {
        for (requestCode in LEGACY_REQUESTS) {
            val pending = PendingIntent.getBroadcast(
                context,
                requestCode,
                refreshIntent(context),
                PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
            ) ?: continue
            alarmManager.cancel(pending)
            pending.cancel()
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

    private fun refreshIntent(context: Context): Intent {
        return Intent(context, RefreshReceiver::class.java).apply {
            action = RefreshReceiver.ACTION_REFRESH
        }
    }

    private fun pendingIntent(context: Context, requestCode: Int): PendingIntent {
        return PendingIntent.getBroadcast(
            context,
            requestCode,
            refreshIntent(context),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }
}
