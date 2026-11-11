plugins {
    kotlin("jvm") version "2.2.21"
}
repositories { mavenCentral() }
dependencies {
    testImplementation(kotlin("test"))
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.11.4")
}
tasks.test {
    useJUnitPlatform()
}
kotlin {
    jvmToolchain(17)
}
