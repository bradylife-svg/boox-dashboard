package io.github.bradylife.booxdashboard

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

class ReloadScheduleTest {
    private val taipei = ZoneId.of("Asia/Taipei")

    @Test
    fun chainsThroughMorningAndEvening() {
        assertSlot(at(4, 50), 5, 15)
        assertSlot(at(5, 15), 5, 45)
        assertSlot(at(8, 20), 8, 45)
        assertSlot(at(8, 46), 17, 15)
        assertSlot(at(20, 45), 5, 15, plusDay = true)
        assertSlot(at(21, 0), 5, 15, plusDay = true)
    }

    private fun at(hour: Int, minute: Int): ZonedDateTime {
        return ZonedDateTime.of(2026, 11, 21, hour, minute, 0, 0, taipei)
    }

    private fun assertSlot(now: ZonedDateTime, hour: Int, minute: Int, plusDay: Boolean = false) {
        val next = AlarmScheduler.nextReload(now)
        assertEquals(hour, next.hour)
        assertEquals(minute, next.minute)
        val expectedDay = if (plusDay) now.toLocalDate().plusDays(1) else now.toLocalDate()
        assertEquals(expectedDay, next.toLocalDate())
    }
}
