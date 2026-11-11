package example.v23
import kotlin.test.Test
import kotlin.test.assertEquals
class CalculatorTest {
    @Test fun verifiesFortyTwo() {
        assertEquals(42, Calculator.add(20, 22))
    }
}
