package example;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;
class GreeterTest {
    @Test void greetingIsCorrect() {
        assertEquals("Hello, JVM", Greeter.greet("JVM"));
    }
}
