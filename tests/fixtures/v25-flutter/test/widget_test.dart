import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:automoto_v25_flutter/main.dart';

void main() {
  testWidgets('V25 app displays the required marker', (WidgetTester tester) async {
    await tester.pumpWidget(const V25App());
    expect(find.byKey(const Key('v25-flutter-marker')), findsOneWidget);
    expect(find.text('V25_FLUTTER_WEB_PASS'), findsOneWidget);
  });
}
