package io.github.bradylife.booxdashboard

import android.content.Context
import android.os.Build
import java.io.File
import java.time.Instant

/**
 * 把未接住的例外寫進應用程式私有檔，下次開啟時顯示。
 * 不需要 adb。檔案是 files/last-crash.txt。
 */
object CrashGuard {
    const val FILE_NAME = "last-crash.txt"

    fun install(context: Context) {
        val app = context.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        if (previous is RecordingHandler) {
            return
        }
        Thread.setDefaultUncaughtExceptionHandler(RecordingHandler(app, previous))
    }

    fun record(context: Context, error: Throwable) {
        val text = buildString {
            appendLine("time=${Instant.now()}")
            appendLine(
                "sdk=${Build.VERSION.SDK_INT} release=${Build.VERSION.RELEASE} " +
                    "device=${Build.MANUFACTURER} ${Build.MODEL}",
            )
            appendLine(error.stackTraceToString())
        }.take(32_000)
        context.applicationContext.openFileOutput(FILE_NAME, Context.MODE_PRIVATE).use { output ->
            output.write(text.toByteArray(Charsets.UTF_8))
        }
    }

    fun read(context: Context): String? {
        val file = File(context.applicationContext.filesDir, FILE_NAME)
        if (!file.exists() || file.length() == 0L) {
            return null
        }
        return file.readText(Charsets.UTF_8).trim().ifEmpty { null }
    }

    fun clear(context: Context) {
        context.applicationContext.deleteFile(FILE_NAME)
    }

    private class RecordingHandler(
        private val app: Context,
        private val previous: Thread.UncaughtExceptionHandler?,
    ) : Thread.UncaughtExceptionHandler {
        override fun uncaughtException(thread: Thread, error: Throwable) {
            try {
                record(app, error)
            } catch (_: Throwable) {
                // 寫檔失敗也不能擋住原本的崩潰處理。
            }
            previous?.uncaughtException(thread, error)
        }
    }
}
