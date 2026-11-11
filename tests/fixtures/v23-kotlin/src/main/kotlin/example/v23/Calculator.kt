package example.v23
object Calculator {
    fun add(a: Int, b: Int): Int = a + b
}
fun main() {
    check(Calculator.add(20, 22) == 42)
    println("V23_KOTLIN_JVM_PASS")
}
