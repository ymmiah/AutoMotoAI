import 'package:flutter/material.dart';

void main() => runApp(const V25App());

class V25App extends StatelessWidget {
  const V25App({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      title: 'AutoMoto V25',
      home: Scaffold(
        body: Center(
          child: Text('V25_FLUTTER_WEB_PASS',
              key: Key('v25-flutter-marker'),
              textDirection: TextDirection.ltr),
        ),
      ),
    );
  }
}
