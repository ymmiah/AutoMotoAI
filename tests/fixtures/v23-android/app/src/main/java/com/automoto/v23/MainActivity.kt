package com.automoto.v23
import android.app.Activity
import android.os.Bundle
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply {
            text = "V23_ANDROID_RUNNING"
            contentDescription = "V23_ANDROID_RUNNING"
            textSize = 22f
        })
    }
}
