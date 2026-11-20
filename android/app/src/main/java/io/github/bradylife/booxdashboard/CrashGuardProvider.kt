package io.github.bradylife.booxdashboard

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri

/** ContentProvider 比 Activity 更早建立，崩潰處理才能接住啟動過程的例外。 */
class CrashGuardProvider : ContentProvider() {
    override fun onCreate(): Boolean {
        try {
            context?.let { CrashGuard.install(it) }
        } catch (_: Throwable) {
        }
        return true
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0
}
