package io.github.bradylife.booxdashboard

import android.util.Log
import android.view.View

/** 盡量觸發 BOOX 全刷。沒有 Onyx SDK 時只做一般 invalidate，不影響其他裝置。 */
object EinkRefresh {
    private const val TAG = "BooxEink"

    fun full(view: View) {
        if (invokeOnyx(view)) {
            return
        }
        view.invalidate()
    }

    private fun invokeOnyx(view: View): Boolean {
        val classNames = arrayOf(
            "com.onyx.android.sdk.api.device.epd.EpdController",
            "android.onyx.epd.EpdController",
        )
        for (name in classNames) {
            try {
                val controller = Class.forName(name)
                val modeClass = Class.forName("$name\$UpdateMode")
                val gc = modeClass.enumConstants?.firstOrNull {
                    it.toString().equals("GC", ignoreCase = true)
                } ?: continue
                val invalidate = controller.methods.firstOrNull { method ->
                    method.name == "invalidate" &&
                        method.parameterTypes.size == 2 &&
                        View::class.java.isAssignableFrom(method.parameterTypes[0])
                }
                if (invalidate != null) {
                    invalidate.invoke(null, view, gc)
                    return true
                }
                val apply = controller.methods.firstOrNull { method ->
                    method.name == "applyGCUpdate" && method.parameterTypes.size == 1
                }
                if (apply != null) {
                    apply.invoke(null, view)
                    return true
                }
            } catch (_: ClassNotFoundException) {
                continue
            } catch (error: Throwable) {
                Log.d(TAG, "略過 $name", error)
            }
        }
        return false
    }
}
